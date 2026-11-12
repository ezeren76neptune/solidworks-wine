// msisql: run SQL against an MSI database through msi.dll (works under Wine).
// usage: msisql <file.msi> ro|rw "<sql>" ["<sql>" ...]   (SELECT rows print tab-separated)
using System;
using System.Runtime.InteropServices;
using System.Text;

static class MsiSql
{
    [DllImport("msi.dll", CharSet = CharSet.Unicode)] static extern uint MsiOpenDatabaseW(string path, IntPtr persist, out uint db);
    [DllImport("msi.dll", CharSet = CharSet.Unicode)] static extern uint MsiDatabaseOpenViewW(uint db, string sql, out uint view);
    [DllImport("msi.dll")] static extern uint MsiViewExecute(uint view, uint rec);
    [DllImport("msi.dll")] static extern uint MsiViewFetch(uint view, out uint rec);
    [DllImport("msi.dll")] static extern uint MsiRecordGetFieldCount(uint rec);
    [DllImport("msi.dll", CharSet = CharSet.Unicode)] static extern uint MsiRecordGetStringW(uint rec, uint field, StringBuilder buf, ref uint len);
    [DllImport("msi.dll")] static extern uint MsiDatabaseCommit(uint db);
    [DllImport("msi.dll")] static extern uint MsiCloseHandle(uint h);

    static int Main(string[] a)
    {
        if (a.Length < 3) { Console.Error.WriteLine("usage: msisql <file.msi> ro|rw <sql>..."); return 2; }
        bool rw = a[1] == "rw";
        uint db;
        uint r = MsiOpenDatabaseW(a[0], (IntPtr)(rw ? 1 : 0), out db);
        if (r != 0) { Console.Error.WriteLine("open failed: " + r); return 1; }
        int rc = 0;
        for (int i = 2; i < a.Length; i++)
        {
            uint view;
            r = MsiDatabaseOpenViewW(db, a[i], out view);
            if (r != 0) { Console.Error.WriteLine("view failed (" + r + "): " + a[i]); rc = 1; continue; }
            r = MsiViewExecute(view, 0);
            if (r != 0) { Console.Error.WriteLine("execute failed (" + r + "): " + a[i]); rc = 1; MsiCloseHandle(view); continue; }
            uint rec;
            while (MsiViewFetch(view, out rec) == 0)
            {
                uint n = MsiRecordGetFieldCount(rec);
                var line = new StringBuilder();
                for (uint f = 1; f <= n; f++)
                {
                    uint len = 0;
                    MsiRecordGetStringW(rec, f, new StringBuilder(1), ref len);
                    len++;
                    var sb = new StringBuilder((int)len);
                    MsiRecordGetStringW(rec, f, sb, ref len);
                    if (f > 1) line.Append('\t');
                    line.Append(sb.ToString());
                }
                Console.WriteLine(line.ToString());
                MsiCloseHandle(rec);
            }
            MsiCloseHandle(view);
        }
        if (rw && rc == 0)
        {
            r = MsiDatabaseCommit(db);
            if (r != 0) { Console.Error.WriteLine("commit failed: " + r); rc = 1; }
        }
        MsiCloseHandle(db);
        return rc;
    }
}
