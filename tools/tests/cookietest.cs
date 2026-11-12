using System; using System.Runtime.InteropServices; using System.Text;
static class T {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct C2 { public string name, value, domain, path; public uint flags, lo, hi; public int set; }
  [DllImport("wininet.dll", CharSet=CharSet.Unicode)] static extern uint InternetSetCookieEx2(string url, ref C2 c, string p3p, uint flags, out uint state);
  [DllImport("wininet.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool InternetGetCookieW(string url, string name, StringBuilder data, ref uint size);
  static int Main() {
    long ft = new DateTime(2031,3,4,5,6,7,DateTimeKind.Utc).ToFileTimeUtc();
    var c = new C2{name="swtest", value="dummy123", domain="test.example", path="/", flags=0, lo=(uint)ft, hi=(uint)(ft>>32), set=1};
    uint st; uint r = InternetSetCookieEx2("http://test.example/", ref c, null, 0, out st);
    var sb = new StringBuilder(512); uint n = 512; bool g = InternetGetCookieW("http://test.example/", null, sb, ref n);
    var c2 = new C2{name="swsess", value="s1", domain="test.example", path="/", flags=0x2000, set=0};
    uint st2; uint r2 = InternetSetCookieEx2("http://test.example/", ref c2, null, 0, out st2);
    Console.WriteLine("set r="+r+" state="+st+" | httponly r="+r2+" state="+st2+" | get="+g+" ["+sb+"]");
    return (r==0 && st==1 && r2==0 && g && sb.ToString().Contains("swtest=dummy123")) ? 0 : 1; } }
