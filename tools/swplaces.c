/* swplaces.dll: registry-driven folder shortcuts for Wine's shell namespace.
 *
 * On Windows a namespace item (an entry under Explorer\Desktop\NameSpace) can
 * point at any folder: its CLSID key carries Instance\InitPropertyBag\Target.
 * Wine's shell32 ignores the Instance key, so such items cannot be added there.
 * Register the item's CLSID with InprocServer32 = this DLL instead: the class
 * factory reads Target and returns Wine's own FolderShortcut folder pointed at
 * it. sync-places.py uses this to put the Linux places (Home, Downloads, ...)
 * in the left pane of Wine's file dialogs.
 *
 * Built by build-pe.sh with MinGW. Exports DllGetClassObject, DllCanUnloadNow. */
#define COBJMACROS
#include <windows.h>
#include <objbase.h>
#include <shlobj.h>
#include <shobjidl.h>

static const CLSID clsid_folder_shortcut =
    {0x0afaced1, 0xe828, 0x11d1, {0x91, 0x87, 0xb5, 0x32, 0xf1, 0xe9, 0x57, 0x5d}};

struct factory
{
    IClassFactory IClassFactory_iface;
    LONG ref;
    CLSID clsid;
};

static struct factory *impl(IClassFactory *iface)
{
    return CONTAINING_RECORD(iface, struct factory, IClassFactory_iface);
}

/* Target of a place: HKCR\CLSID\{clsid}\Instance\InitPropertyBag "Target" (env vars expanded). */
static HRESULT read_target(REFCLSID clsid, WCHAR target[MAX_PATH])
{
    WCHAR key[96], guid[40];
    DWORD size = MAX_PATH * sizeof(WCHAR);

    if (!StringFromGUID2(clsid, guid, ARRAYSIZE(guid)))
        return E_FAIL;
    lstrcpyW(key, L"CLSID\\");
    lstrcatW(key, guid);
    lstrcatW(key, L"\\Instance\\InitPropertyBag");
    /* RRF_RT_REG_SZ also accepts REG_EXPAND_SZ and expands it (asking for
     * RRF_RT_REG_EXPAND_SZ without RRF_NOEXPAND is an invalid parameter) */
    if (RegGetValueW(HKEY_CLASSES_ROOT, key, L"Target", RRF_RT_REG_SZ, NULL, target, &size) || !target[0])
        return CLASS_E_CLASSNOTAVAILABLE;
    return S_OK;
}

static HRESULT WINAPI factory_QueryInterface(IClassFactory *iface, REFIID riid, void **ppv)
{
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IClassFactory))
    {
        *ppv = iface;
        IClassFactory_AddRef(iface);
        return S_OK;
    }
    *ppv = NULL;
    return E_NOINTERFACE;
}

static ULONG WINAPI factory_AddRef(IClassFactory *iface)
{
    return InterlockedIncrement(&impl(iface)->ref);
}

static ULONG WINAPI factory_Release(IClassFactory *iface)
{
    struct factory *f = impl(iface);
    ULONG ref = InterlockedDecrement(&f->ref);

    if (!ref)
        HeapFree(GetProcessHeap(), 0, f);
    return ref;
}

static HRESULT WINAPI factory_CreateInstance(IClassFactory *iface, IUnknown *outer, REFIID riid, void **ppv)
{
    HRESULT (WINAPI *shell32_get_class)(REFCLSID, REFIID, void **);
    PERSIST_FOLDER_TARGET_INFO info;
    IClassFactory *shell_factory;
    IPersistFolder3 *folder;
    HMODULE shell32;
    HRESULT hr;

    if (!ppv)
        return E_POINTER;
    *ppv = NULL;
    if (outer)
        return CLASS_E_NOAGGREGATION;

    memset(&info, 0, sizeof(info));
    if (FAILED(hr = read_target(&impl(iface)->clsid, info.szTargetParsingName)))
        return hr;
    info.dwAttributes = (DWORD)-1;
    info.csidl = -1;

    /* Ask shell32 directly rather than through CoCreateInstance, so the folder
     * lives in the caller's apartment whatever its threading model. */
    if (!(shell32 = LoadLibraryW(L"shell32.dll")))
        return HRESULT_FROM_WIN32(GetLastError());
    shell32_get_class = (void *)GetProcAddress(shell32, "DllGetClassObject");
    if (!shell32_get_class)
        return CLASS_E_CLASSNOTAVAILABLE;
    if (FAILED(hr = shell32_get_class(&clsid_folder_shortcut, &IID_IClassFactory, (void **)&shell_factory)))
        return hr;
    hr = IClassFactory_CreateInstance(shell_factory, NULL, &IID_IPersistFolder3, (void **)&folder);
    IClassFactory_Release(shell_factory);
    if (FAILED(hr))
        return hr;

    /* The shell then calls IPersistFolder::Initialize with the item's pidl,
     * which a FolderShortcut takes as its location while keeping this target. */
    hr = IPersistFolder3_InitializeEx(folder, NULL, NULL, &info);
    if (SUCCEEDED(hr))
        hr = IPersistFolder3_QueryInterface(folder, riid, ppv);
    IPersistFolder3_Release(folder);
    return hr;
}

static HRESULT WINAPI factory_LockServer(IClassFactory *iface, BOOL lock)
{
    return S_OK;
}

static const IClassFactoryVtbl factory_vtbl =
{
    factory_QueryInterface,
    factory_AddRef,
    factory_Release,
    factory_CreateInstance,
    factory_LockServer,
};

HRESULT WINAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void **ppv)
{
    WCHAR target[MAX_PATH];
    struct factory *f;
    HRESULT hr;

    if (!ppv)
        return E_POINTER;
    *ppv = NULL;
    if (FAILED(read_target(clsid, target)))
        return CLASS_E_CLASSNOTAVAILABLE;
    if (!(f = HeapAlloc(GetProcessHeap(), 0, sizeof(*f))))
        return E_OUTOFMEMORY;
    f->IClassFactory_iface.lpVtbl = (IClassFactoryVtbl *)&factory_vtbl;
    f->ref = 1;
    f->clsid = *clsid;
    hr = IClassFactory_QueryInterface(&f->IClassFactory_iface, riid, ppv);
    IClassFactory_Release(&f->IClassFactory_iface);
    return hr;
}

HRESULT WINAPI DllCanUnloadNow(void)
{
    return S_FALSE;
}
