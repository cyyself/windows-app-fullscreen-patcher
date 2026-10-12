#!/usr/bin/env python3
"""Patch decoded Windows App smali so RDP sessions draw under the display cutout.

Usage: patch_smali.py <apktool-decoded-dir> [--package NEW_ID] [--label NAME]
Every patch asserts it matched, so an app update that moves the code fails loudly
instead of producing a silently unpatched APK.
"""
import argparse
import glob
import re
import sys

ap = argparse.ArgumentParser()
ap.add_argument('root')
ap.add_argument('--package', help='new application id, so the patch installs beside the official app')
ap.add_argument('--label', help='launcher label to tell the two apps apart')
args = ap.parse_args()
root = args.root
OLD_PKG = 'com.microsoft.rdc.androidx'


def one(pattern):
    files = glob.glob(f'{root}/smali*/{pattern}')
    if len(files) != 1:
        sys.exit(f'expected exactly one file for {pattern}, found {files}')
    return files[0]


def rewrite(path, fn):
    with open(path) as f:
        s = f.read()
    s, n = fn(s)
    with open(path, 'w') as f:
        f.write(s)
    return n


# 1. Session screen (Compose): drop Modifier.windowInsetsPadding(WindowInsets.displayCutout).
#    Present up to 11.0.26071; 11.0.26081 removed it upstream, so this one is optional.
#    The obfuscated WindowInsetsHolder field is found via its "displayCutout" name string.
holder = one('androidx/compose/foundation/layout/WindowInsetsHolder.smali')
m = re.search(r'const-string (v\d+), "displayCutout"\n.*?iput-object v\d+, v\d+, '
              r'Landroidx/compose/foundation/layout/WindowInsetsHolder;->(\w+):', open(holder).read(), re.S)
if not m:
    sys.exit('[1] WindowInsetsHolder.displayCutout field not found')
padding = re.compile(
    rf'(iget-object (v\d+), \2, Landroidx/compose/foundation/layout/WindowInsetsHolder;->{m.group(2)}:[^\n]*\n\s*\n)'
    r'\s*invoke-static \{(v\d+), \2\}, Landroidx/compose/foundation/layout/WindowInsetsPaddingKt;->\w+\([^\n]*\n\s*\n'
    r'\s*move-result-object \3\n')
n = rewrite(one('com/microsoft/a3rdc/ui/activities/session/SessionScreenKt.smali'),
            lambda s: padding.subn(r'\1', s))
if n > 1:
    sys.exit(f'[1] session Compose padding matched {n}x, expected at most 1')
print('[1] session Compose cutout padding removed' if n else '[1] session Compose cutout padding not present (removed upstream)')

# 2. Size the remote desktop from the full screen: DisplayCutout.getSafeInset*() -> 0.
safe_inset = re.compile(
    r'invoke-virtual \{(?:v|p)\d+\}, Landroid/view/DisplayCutout;->getSafeInset(?:Left|Right|Top|Bottom)\(\)I\n'
    r'(\s*)\n(\s*)move-result ((?:v|p)\d+)')
total = 0
for path in (glob.glob(f'{root}/smali*/com/microsoft/a3rdc/desktop/ScreenDimensions*.smali')
             + glob.glob(f'{root}/smali*/com/microsoft/windowsapp/display_helper/provider/DisplayInfoProvider.smali')):
    total += rewrite(path, lambda s: safe_inset.subn(lambda m: f'const/16 {m.group(3)}, 0x0\n{m.group(1)}\n{m.group(2)}nop', s))
if total == 0:
    sys.exit('[2] no DisplayCutout.getSafeInset* calls found')
print(f'[2] {total} cutout safe-inset reads zeroed')

# 3. Legacy session root: skip the BasePresenterActivity helper that pads a view by systemBars|displayCutout
#    (U0 / V0 depending on version; found as the (View)V method installing an OnApplyWindowInsetsListener).
#    The bars are hidden during a session, so only the cutout was contributing.
base = open(one('com/microsoft/a3rdc/ui/activities/BasePresenterActivity.smali')).read()
helpers = [name for name, body in re.findall(r'\.method [^\n]*?(\w+)\(Landroid/view/View;\)V\n(.*?)\.end method', base, re.S)
           if 'Landroidx/core/view/OnApplyWindowInsetsListener;)V' in body]
if len(helpers) != 1:
    sys.exit(f'[3] expected one inset helper in BasePresenterActivity, found {helpers}')
u0 = re.compile(rf'\n\s*invoke-(?:static|virtual) \{{[vp\d, ]+\}}, Lcom/microsoft/a3rdc/ui/activities/\w+;->{helpers[0]}\(Landroid/view/View;\)V\n')
n = rewrite(one('com/microsoft/a3rdc/ui/activities/LegacySessionActivity.smali'), lambda s: u0.subn('\n', s))
if n != 1:
    sys.exit(f'[3] session_root inset padding ({helpers[0]}) matched {n}x, expected 1')
print(f'[3] session_root inset padding ({helpers[0]}) removed')

# 4. Optional: new application id. Code calls getPackageName() rather than hard-coding the id,
#    so renaming the manifest package plus the system-wide-unique names (provider authorities,
#    custom permissions, deep-link host) is enough.
if args.package:
    def manifest(s):
        # Safe to rewrite package= directly: every component name in the manifest is fully qualified.
        if re.search(r'android:name="\.', s):
            sys.exit('[4] manifest has relative component names; package rename would break them')
        s, n = re.subn(rf'(<manifest [^>]*package="){re.escape(OLD_PKG)}"', rf'\g<1>{args.package}"', s)
        if n != 1:
            sys.exit('[4] manifest package attribute not found')
        old = re.escape(OLD_PKG)
        for pat in (rf'(android:authorities="){old}([."])',
                    rf'(android:host="){old}([."])',
                    rf'(<(?:uses-)?permission [^>]*android:name="){old}([."])'):
            s, k = re.subn(pat, rf'\g<1>{args.package}\2', s)
            n += k
        return s, n
    n = rewrite(f'{root}/AndroidManifest.xml', manifest)
    print(f'[4] application id -> {args.package} ({n} manifest edits)')

    # The app starts sessions/editors with implicit intents (e.g. com.microsoft.windowsapp.action.SESSION_START,
    # no package set). With both apps installed, each would match the other's activities, prompting a chooser
    # that "Always" makes stick. Give this build its own action names, in the manifest and in the code.
    action = r'com\.microsoft\.windowsapp\.((?:action\.)?[A-Z][A-Z_]*)'
    n = rewrite(f'{root}/AndroidManifest.xml',
                lambda s: re.subn(rf'(<action android:name="){action}"', rf'\g<1>{args.package}.\2"', s))
    if n == 0:
        sys.exit('[4] no com.microsoft.windowsapp intent actions found in manifest')
    k = 0
    for path in glob.glob(f'{root}/smali*/**/*.smali', recursive=True):
        with open(path) as f:
            if 'com.microsoft.windowsapp.' not in f.read():
                continue
        k += rewrite(path, lambda s: re.subn(rf'(const-string(?:/jumbo)? [vp]\d+, "){action}"',
                                             rf'\g<1>{args.package}.\2"', s))
    print(f'[4] intent actions -> {args.package}.* ({n} manifest, {k} code)')

if args.label:
    n = 0
    for path in glob.glob(f'{root}/res/values*/strings.xml'):
        n += rewrite(path, lambda s: re.subn(r'(<string name="app_name">)[^<]*(</string>)',
                                             lambda m: m.group(1) + args.label + m.group(2), s))
    print(f'[5] launcher label -> {args.label} ({n} locales)')
