using System; using System.Runtime.InteropServices;
static class T {
  [StructLayout(LayoutKind.Sequential)] struct U { public ushort L, M; public IntPtr B; }
  [DllImport("ntdll.dll")] static extern byte RtlIsNameInExpression(ref U e, ref U n, byte ic, IntPtr t);
  static U Mk(string s) { U u; u.L=(ushort)(s.Length*2); u.M=u.L; u.B=Marshal.StringToHGlobalUni(s); return u; }
  static int Main() { int bad=0; object[][] c={
    new object[]{"*.DIC","AFRCORE.DIC",true,true}, new object[]{"*.DIC","AfrCore.dic",true,true}, new object[]{"*.DIC","AFRCORE.IID",true,false},
    new object[]{"*","anything",false,true}, new object[]{"A?C","ABC",false,true}, new object[]{"A?C","ABBC",false,false},
    new object[]{"*.*","noext",false,false}, new object[]{"<.DIC","A.B.DIC",true,true}, new object[]{"A*B*C","AXXBYYC",false,true}, new object[]{"ABC","abc",false,false}};
    foreach(var x in c){ U e=Mk((string)x[0]), n=Mk((string)x[1]); bool r=RtlIsNameInExpression(ref e, ref n, (byte)((bool)x[2]?1:0), IntPtr.Zero)!=0; bool ok=r==(bool)x[3]; if(!ok)bad++; Console.WriteLine((ok?"ok   ":"FAIL ")+x[0]+" vs "+x[1]+" -> "+r); }
    Console.WriteLine("failures: "+bad); return bad; } }
