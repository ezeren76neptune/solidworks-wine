#!/usr/bin/env python3
"""Write C:\\DSInstall\\sw-install.json, the answer file the SOLIDWORKS installer reads.

usage: make-install-json.py --tenant OI000123456 [--region us1] [--registry-region eu1]

--tenant   your 3DEXPERIENCE platform ID: the part before "-us1-..." in the
           platform's web address (https://oi000123456-us1-makers-space...),
           in capitals.
--region   the region in that address (us1, eu1, ...). Default us1.
--registry-region  region of the Makers registry and sign-in service. Default
           eu1 (what the tested Makers account used for both).

On a Windows machine where SOLIDWORKS was installed from the platform, the same
values appear in the installer command line in the 3DEXPERIENCE Launcher's
logs; prefer those if you have them. The file must be a JSON *list*.
"""
import argparse, getpass, json, os

ap = argparse.ArgumentParser()
ap.add_argument('--tenant', required=True)
ap.add_argument('--region', default='us1')
ap.add_argument('--registry-region', default='eu1')
ap.add_argument('--media', default='SOLIDWORKS_3DEXP_Desktop.Full.Windows64')
ap.add_argument('--download', default='https://3ds-software-us-east-1.s3-external-1.amazonaws.com/V6/R428/'
                'PINPOINT/T6PP9/SOLIDWORKS_3DEXP_Desktop.Full.Windows64_package/OIF/CAFS/')
ap.add_argument('--out', help='default: $WINEPREFIX/drive_c/DSInstall/sw-install.json')
a = ap.parse_args()

tenant = a.tenant.upper()
host = '%s-%s-makers' % (tenant.lower(), a.region)
registry = 'https://%s-makers-registry.3dexperience.3ds.com' % a.registry_region
apps = 'https://%s-compass.3dexperience.3ds.com:443/enovia/resources/AppsMngt' % host
products = 'DRA DRB DRS E3D IYW SWXCSWK_RP SWXCVIZ_RP SWXMOSI_RP SWXSIMO_RP U3WCSWK_RP UYW W4Y XSM XWA XWB XWC XWD'
v = {
    '3DRegistryURL': registry,
    'MyAppsURL': apps + '/',
    'NativeAppsShortcutObject': '-Url=https://%s-space.3dexperience.3ds.com:443/enovia --AppName="SWXCSWK_AP" '
                                '-MyAppsURL=%s -tenant=%s -monoapp  -RegistryUrl=%s -3DRegistryURL=%s'
                                % (host, apps, tenant, registry, registry),
    'PassportUrl': 'https://%s-makers.iam.3dexperience.3ds.com' % a.registry_region,
    'SelectProduct': '',
}
for p in products.split():                    # XWB = SOLIDWORKS Design for Makers
    v['SelectProduct?CODE\\win_b64\\%s.prd' % p] = 'true' if p == 'XWB' else 'false'
v['TARGET_PATH'] = r'C:\Program Files\Dassault Systemes\SOLIDWORKS 3DEXPERIENCE R2026x'
v['tenant'] = tenant
env = {
    'DSYAdmInstAllowNonCommittedInstall': '1',
    'DSY_Online_Installation_Caf_Repositiory':      # sic: Dassault's spelling
        r'C:\ProgramData\DassaultSystemes\3DEXPERIENCELauncher\defaultDataStore\Cafs\R428',
    'DSY_Online_Installation_DownloadPlatform': a.download,
    'DSY_Online_Installation_User': getpass.getuser(),
}
vol = 'C:\\DSInstall\\' + a.media
doc = [{'mode': 'install', 'data': {'volumes': ['%s\\%d' % (vol, i) for i in range(1, 9)], 'vars': v, 'env': env}}]
out = a.out or os.path.join(os.environ.get('WINEPREFIX') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'prefix'),
                            'drive_c', 'DSInstall', 'sw-install.json')
os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(doc, open(out, 'w'))
print(out)
