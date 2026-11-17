using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

namespace Ciceron
{
    public static class ShellLinkProperties
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct PropertyKey
        {
            public Guid Format;
            public uint Id;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct PropVariant
        {
            public ushort Type;
            private ushort reserved1, reserved2, reserved3;
            public IntPtr Pointer;
            private IntPtr vectorPointer;
        }

        [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IPropertyStore
        {
            void GetCount(out uint count);
            void GetAt(uint index, out PropertyKey key);
            void GetValue(ref PropertyKey key, out PropVariant value);
            void SetValue(ref PropertyKey key, ref PropVariant value);
            void Commit();
        }

        [DllImport("propsys.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
        private static extern int PSGetPropertyKeyFromName(string name, out PropertyKey key);

        [DllImport("propsys.dll", ExactSpelling = true)]
        private static extern int InitPropVariantFromStringVector(
            [MarshalAs(UnmanagedType.LPArray, ArraySubType = UnmanagedType.LPWStr)] string[] values,
            uint count, out PropVariant value);

        [DllImport("ole32.dll", ExactSpelling = true)]
        private static extern int PropVariantClear(ref PropVariant value);

        private static void SetProperty(IPropertyStore store, string name, PropVariant value)
        {
            try
            {
                PropertyKey key;
                Marshal.ThrowExceptionForHR(PSGetPropertyKeyFromName(name, out key));
                store.SetValue(ref key, ref value);
            }
            finally
            {
                PropVariantClear(ref value);
            }
        }

        public static void Set(string path, string appId, string[] tags)
        {
            var link = Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("00021401-0000-0000-C000-000000000046")));
            try
            {
                var file = (IPersistFile)link;
                file.Load(path, 2); // STGM_READWRITE
                var store = (IPropertyStore)link;
                SetProperty(store, "System.AppUserModel.ID", new PropVariant {
                    Type = (ushort)VarEnum.VT_LPWSTR, Pointer = Marshal.StringToCoTaskMemUni(appId)
                });
                PropVariant keywords;
                Marshal.ThrowExceptionForHR(InitPropVariantFromStringVector(tags, (uint)tags.Length, out keywords));
                SetProperty(store, "System.Keywords", keywords);
                store.Commit();
                file.Save(path, true);
            }
            finally
            {
                Marshal.ReleaseComObject(link);
            }
        }
    }
}
