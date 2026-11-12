// msifeat: print the installed state of every feature of a product (works under Wine).
// usage: msifeat <ProductCode> <file.msi>     state: 3=local 2=absent 1=advertised -1=unknown
using System;
using System.Runtime.InteropServices;
using System.Text;

static class MsiFeat
{
    [DllImport("msi.dll", CharSet = CharSet.Unicode)] static extern uint MsiOpenDatabaseW(string path, IntPtr persist, out uint db);
    [DllImport("msi.dll", CharSet = CharSet.Unicode)] static extern uint MsiDatabaseOpenViewW(uint db, string sql, out uint view);
    [DllImport("msi.dll")] static extern uint MsiViewExecute(uint view, uint rec);
    [DllImport("msi.dll")] static extern uint MsiViewFetch(uint view, out uint rec);
    [DllImport("msi.dll", CharSet = CharSet.Unicode)] static extern uint MsiRecordGetStringW(uint rec, uint field, StringBuilder buf, ref uint len);
    [DllImport("msi.dll")] static extern uint MsiCloseHandle(uint h);
    [DllImport("msi.dll", CharSet = CharSet.Unicode)] static extern int MsiQueryFeatureStateW(string product, string feature);

    static int Main(string[] a)
    {
        uint db, view, rec;
        if (MsiOpenDatabaseW(a[1], IntPtr.Zero, out db) != 0) { Console.Error.WriteLine("open failed"); return 1; }
        MsiDatabaseOpenViewW(db, "SELECT `Feature` FROM `Feature`", out view);
        MsiViewExecute(view, 0);
        while (MsiViewFetch(view, out rec) == 0)
        {
            uint len = 256; var sb = new StringBuilder(256);
            MsiRecordGetStringW(rec, 1, sb, ref len);
            Console.WriteLine(sb + "\t" + MsiQueryFeatureStateW(a[0], sb.ToString()));
            MsiCloseHandle(rec);
        }
        MsiCloseHandle(view); MsiCloseHandle(db);
        return 0;
    }
}
