/* Additions to a private copy of Wine's ntdll.dll for Dassault's V6 runtime
 * (3DEXPERIENCE SOLIDWORKS). Built as a position-independent blob with no
 * imports and injected by pe-inject.py, which fills each slot_<Export> with the
 * distance to that ntdll export and each symslot_<name> with the distance to
 * that internal ntdll variable (from the DLL's COFF symbol table).
 *
 * 1. RtlIsNameInExpression: see rtl_isnameinexpression.c.
 * 2. LdrpHandleTlsData / LdrpReleaseTlsEntry: Dassault's in-memory DLL loader
 *    (used for its licensing module) finds these non-exported Windows loader
 *    functions by scanning ntdll's .text/.rdata, and refuses to load a module
 *    that has a TLS directory when they are missing. They are implemented here
 *    on Wine's own TLS tables, mirroring alloc_tls_slot()/free_tls_slot() in
 *    wine/dlls/ntdll/loader.c, so new threads get the module's TLS block too. */
#include "rtl_isnameinexpression.c"

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long u64;

#define WINAPI __attribute__((ms_abi))
#define SLOT(name) __attribute__((used)) const volatile int name = 0x5a5a5a5a
#define AT(slot) ((const char *)&slot + slot)

SLOT(slot_RtlImageDirectoryEntryToData);
SLOT(slot_RtlAllocateHeap);
SLOT(slot_RtlReAllocateHeap);
SLOT(slot_RtlFreeHeap);
SLOT(slot_NtGetNextThread);
SLOT(slot_NtClose);
SLOT(slot_NtQueryInformationThread);
SLOT(slot_LdrLockLoaderLock);
SLOT(slot_LdrUnlockLoaderLock);
SLOT(symslot_tls_dirs);          /* static IMAGE_TLS_DIRECTORY *tls_dirs */
SLOT(symslot_tls_module_count);  /* static UINT tls_module_count */

typedef void *(WINAPI *fn_dirdata)(void *base, u8 image, unsigned short dir, u32 *size);
typedef void *(WINAPI *fn_alloc)(void *heap, u32 flags, u64 size);
typedef void *(WINAPI *fn_realloc)(void *heap, u32 flags, void *ptr, u64 size);
typedef u8 (WINAPI *fn_free)(void *heap, u32 flags, void *ptr);
typedef int (WINAPI *fn_next_thread)(void *process, void *thread, u32 access, u32 attr, u32 flags, void **handle);
typedef int (WINAPI *fn_close)(void *handle);
typedef int (WINAPI *fn_query_thread)(void *thread, int info_class, void *info, u32 len, u32 *ret_len);
typedef int (WINAPI *fn_lock)(u32 flags, u32 *result, u64 *magic);
typedef int (WINAPI *fn_unlock)(u32 flags, u64 magic);

typedef struct
{
    u64 StartAddressOfRawData, EndAddressOfRawData, AddressOfIndex, AddressOfCallBacks;
    u32 SizeOfZeroFill, Characteristics;
} TLSDIR;

#define HEAP_ZERO_MEMORY 8
#define THREAD_QUERY_LIMITED_INFORMATION 0x800
#define IMAGE_DIRECTORY_ENTRY_TLS 9
#define TEB_TLS_POINTER 0x58
#define LDR_DLLBASE 0x30
#define LDR_TLSINDEX 0x6e
#define STATUS_NO_MEMORY ((int)0xc0000017)

static inline void *process_heap(void)
{
    char *peb;
    __asm__("movq %%gs:0x60,%0" : "=r"(peb));
    return *(void **)(peb + 0x30);
}

static void copy(void *dst, const void *src, u64 n)
{
    u8 *d = dst;
    const u8 *s = src;
    while (n--) *d++ = *s++;
}

static void zero(void *dst, u64 n)
{
    volatile u8 *d = dst;
    while (n--) *d++ = 0;
}

static const TLSDIR *tls_directory(void *base)
{
    u32 size;
    return ((fn_dirdata)AT(slot_RtlImageDirectoryEntryToData))(base, 1, IMAGE_DIRECTORY_ENTRY_TLS, &size);
}

/* returns 1 if a slot was allocated, 0 if the module needs none, -1 on failure */
static int alloc_tls_slot(void *base)
{
    TLSDIR **pdirs = (TLSDIR **)AT(symslot_tls_dirs), *dirs;
    u32 *pcount = (u32 *)AT(symslot_tls_module_count);
    fn_alloc alloc = (fn_alloc)AT(slot_RtlAllocateHeap);
    fn_free hfree = (fn_free)AT(slot_RtlFreeHeap);
    fn_close close = (fn_close)AT(slot_NtClose);
    const TLSDIR *dir = tls_directory(base);
    void *heap = process_heap(), *thread = 0, *next, *block;
    u32 i, size, old_count = *pcount;

    if (!dir) return 0;
    size = (u32)(dir->EndAddressOfRawData - dir->StartAddressOfRawData);
    if (!size && !dir->SizeOfZeroFill && !dir->AddressOfCallBacks) return 0;

    dirs = *pdirs;
    for (i = 0; i < *pcount; i++)
        if (!dirs[i].StartAddressOfRawData && !dirs[i].EndAddressOfRawData &&
            !dirs[i].SizeOfZeroFill && !dirs[i].AddressOfCallBacks) break;

    if (i == *pcount)
    {
        u32 new_count = *pcount * 2;
        dirs = ((fn_realloc)AT(slot_RtlReAllocateHeap))(heap, HEAP_ZERO_MEMORY, dirs, (u64)new_count * sizeof(*dirs));
        if (!dirs) return -1;
        *pdirs = dirs;
        *pcount = new_count;
    }

    /* allocate the data block in all running threads */
    while (!((fn_next_thread)AT(slot_NtGetNextThread))((void *)-1, thread, THREAD_QUERY_LIMITED_INFORMATION, 0, 0, &next))
    {
        u64 tbi[6];   /* THREAD_BASIC_INFORMATION, TebBaseAddress at +8 */
        char *teb;
        void **tls;

        if (thread) close(thread);
        thread = next;
        if (((fn_query_thread)AT(slot_NtQueryInformationThread))(thread, 0, tbi, sizeof(tbi), 0)) continue;
        if (!(teb = (char *)tbi[1])) continue;
        /* thread not initialized by the loader yet, or already torn down */
        if (!(tls = *(void ***)(teb + TEB_TLS_POINTER))) continue;

        if (old_count < *pcount)
        {
            void **grown = alloc(heap, HEAP_ZERO_MEMORY, (u64)*pcount * sizeof(void *));
            if (!grown) { close(thread); return -1; }
            copy(grown, tls, (u64)old_count * sizeof(void *));
            *(void ***)(teb + TEB_TLS_POINTER) = tls = grown;
            /* like Wine, the old array is left for thread exit */
        }

        if (!(block = alloc(heap, 0, (u64)size + dir->SizeOfZeroFill))) { close(thread); return -1; }
        copy(block, (const void *)dir->StartAddressOfRawData, size);
        zero((char *)block + size, dir->SizeOfZeroFill);
        hfree(heap, 0, __atomic_exchange_n(&tls[i], block, __ATOMIC_SEQ_CST));
    }
    if (thread) close(thread);

    *(u32 *)dir->AddressOfIndex = i;
    dirs[i] = *dir;
    return 1;
}

/* NTSTATUS LdrpHandleTlsData(LDR_DATA_TABLE_ENTRY *entry) */
WINAPI int LdrpHandleTlsData_impl(void *entry)
{
    u64 magic = 0;
    int r;

    if (!entry) return 0;
    ((fn_lock)AT(slot_LdrLockLoaderLock))(0, 0, &magic);
    r = alloc_tls_slot(*(void **)((char *)entry + LDR_DLLBASE));
    ((fn_unlock)AT(slot_LdrUnlockLoaderLock))(0, magic);
    if (r < 0) return STATUS_NO_MEMORY;
    if (r) *(unsigned short *)((char *)entry + LDR_TLSINDEX) = 0xffff;
    return 0;
}

/* void LdrpReleaseTlsEntry(LDR_DATA_TABLE_ENTRY *entry, void *unused) */
WINAPI int LdrpReleaseTlsEntry_impl(void *entry, void *unused)
{
    TLSDIR **pdirs = (TLSDIR **)AT(symslot_tls_dirs);
    u32 *pcount = (u32 *)AT(symslot_tls_module_count);
    const TLSDIR *dir;
    u64 magic = 0;
    u32 i;

    (void)unused;
    if (!entry) return 0;
    ((fn_lock)AT(slot_LdrLockLoaderLock))(0, 0, &magic);
    if ((dir = tls_directory(*(void **)((char *)entry + LDR_DLLBASE))) && dir->AddressOfIndex)
    {
        i = *(u32 *)dir->AddressOfIndex;
        /* only clear the slot if it is really this module's */
        if (i < *pcount && (*pdirs)[i].AddressOfIndex == dir->AddressOfIndex) zero(&(*pdirs)[i], sizeof(TLSDIR));
    }
    ((fn_unlock)AT(slot_LdrUnlockLoaderLock))(0, magic);
    return 0;
}
