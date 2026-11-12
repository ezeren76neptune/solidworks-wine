using System; using System.Runtime.InteropServices; using System.Threading;
static class T {
  [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr LoadLibraryExW(string p, IntPtr h, uint flags);
  [DllImport("ntdll")] static extern int LdrpHandleTlsData(IntPtr entry);
  [DllImport("ntdll")] static extern int LdrpReleaseTlsEntry(IntPtr entry, IntPtr x);
  [DllImport("ntdll")] static extern int NtQueryInformationThread(IntPtr h, int cls, byte[] buf, int len, IntPtr ret);
  [DllImport("kernel32")] static extern IntPtr GetCurrentThread();
  static IntPtr Teb() { var b = new byte[0x30]; NtQueryInformationThread(GetCurrentThread(), 0, b, 0x30, IntPtr.Zero); return (IntPtr)BitConverter.ToInt64(b, 8); }
  static long TlsBlock(uint index) { IntPtr arr = Marshal.ReadIntPtr(Teb(), 0x58); return arr == IntPtr.Zero ? 0 : Marshal.ReadInt64(arr, (int)index * 8); }
  static int Main(string[] a) {
    IntPtr mod = LoadLibraryExW(a[0], IntPtr.Zero, 1);
    if (mod == IntPtr.Zero) { Console.WriteLine("load failed " + Marshal.GetLastWin32Error()); return 2; }
    long b = mod.ToInt64(); int pe = Marshal.ReadInt32(mod, 0x3c);
    int tlsRva = Marshal.ReadInt32(mod, pe + 0x88 + 9*8), tlsSize = Marshal.ReadInt32(mod, pe + 0x88 + 9*8 + 4);
    Console.WriteLine("module " + b.ToString("x") + " tls rva " + tlsRva.ToString("x") + " size " + tlsSize);
    if (tlsRva == 0) return 3;
    IntPtr dir = (IntPtr)(b + tlsRva);
    long start = Marshal.ReadInt64(dir, 0), end = Marshal.ReadInt64(dir, 8), pidx = Marshal.ReadInt64(dir, 16); int zf = Marshal.ReadInt32(dir, 32);
    uint before = (uint)Marshal.ReadInt32((IntPtr)pidx);
    IntPtr entry = Marshal.AllocHGlobal(0x278); for (int i = 0; i < 0x278; i += 8) Marshal.WriteInt64(entry, i, 0);
    Marshal.WriteInt64(entry, 0x30, b);
    long other = TlsBlock(0);
    int st = LdrpHandleTlsData(entry);
    uint idx = (uint)Marshal.ReadInt32((IntPtr)pidx);
    long blk = TlsBlock(idx);
    bool same = blk != 0; for (int i = 0; same && i < Math.Min(end - start, 256); i++) if (Marshal.ReadByte((IntPtr)(blk + i)) != Marshal.ReadByte((IntPtr)(start + i))) same = false;
    long tblk = 0; var th = new Thread(() => { tblk = TlsBlock(idx); }); th.Start(); th.Join();
    Console.WriteLine("status " + st + " index " + before + " -> " + idx + " TlsIndex field " + Marshal.ReadInt16(entry, 0x6e) + " block " + blk.ToString("x") + " template " + (end - start) + "+" + zf + " bytes, matches " + same + ", slot0 kept " + (other == TlsBlock(0)) + ", new-thread block " + tblk.ToString("x"));
    int st2 = LdrpReleaseTlsEntry(entry, IntPtr.Zero);
    long tblk2 = -1; var th2 = new Thread(() => { tblk2 = TlsBlock(idx); }); th2.Start(); th2.Join();
    Console.WriteLine("release " + st2 + ", new-thread block after release " + tblk2.ToString("x"));
    bool ok = st == 0 && idx != before && blk != 0 && same && tblk != 0 && tblk != blk && tblk2 == 0;
    Console.WriteLine(ok ? "PASS" : "FAIL"); return ok ? 0 : 1; } }
