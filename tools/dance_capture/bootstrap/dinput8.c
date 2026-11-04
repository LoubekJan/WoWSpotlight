#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <unknwn.h>
#include <strsafe.h>

typedef HRESULT (WINAPI *DirectInput8CreateFn)(HINSTANCE, DWORD, const IID *, LPVOID *, LPUNKNOWN);

static INIT_ONCE initialized = INIT_ONCE_STATIC_INIT;
static DirectInput8CreateFn systemDirectInput8Create;

HRESULT WINAPI SpotlightDirectInput8Create(HINSTANCE instance, DWORD version, const IID *interfaceId,
                                           LPVOID *output, LPUNKNOWN outer);

static BOOL isFile(const wchar_t *path)
{
    DWORD attributes = GetFileAttributesW(path);
    return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

static DWORD WINAPI startCompanion(LPVOID parameter)
{
    wchar_t clientDir[MAX_PATH];
    wchar_t python[MAX_PATH];
    wchar_t script[MAX_PATH];
    wchar_t command[3 * MAX_PATH + 64];
    DWORD length = GetModuleFileNameW(NULL, clientDir, ARRAYSIZE(clientDir));
    wchar_t *separator;
    STARTUPINFOW startup = {0};
    PROCESS_INFORMATION child = {0};

    (void)parameter;
    if (!length || length >= ARRAYSIZE(clientDir))
        return 0;

    separator = wcsrchr(clientDir, L'\\');
    if (!separator)
        return 0;
    *separator = L'\0';

    if (FAILED(StringCchPrintfW(python, ARRAYSIZE(python), L"%ls\\Spotlight\\Runtime\\pythonw.exe", clientDir))
        || FAILED(StringCchPrintfW(script, ARRAYSIZE(script), L"%ls\\Spotlight\\Companion\\spotlight_client.py", clientDir))
        || !isFile(python) || !isFile(script))
        return 0;

    if (FAILED(StringCchPrintfW(command, ARRAYSIZE(command),
                                L"\"%ls\" -I -B \"%ls\" --client-dir \"%ls\" --client-pid %lu",
                                python, script, clientDir, GetCurrentProcessId())))
        return 0;

    startup.cb = sizeof(startup);
    if (CreateProcessW(python, command, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, clientDir, &startup, &child)) {
        CloseHandle(child.hThread);
        CloseHandle(child.hProcess);
    }
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved)
{
    (void)instance;
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        /* The worker cannot run until DLL initialization returns. Never wait here. */
        HANDLE worker = CreateThread(NULL, 0, startCompanion, NULL, 0, NULL);
        if (worker)
            CloseHandle(worker);
    }
    return TRUE;
}

static BOOL CALLBACK initialize(PINIT_ONCE once, PVOID parameter, PVOID *context)
{
    wchar_t systemPath[MAX_PATH];
    UINT length = GetSystemDirectoryW(systemPath, ARRAYSIZE(systemPath));
    HMODULE systemDinput;

    (void)once;
    (void)parameter;
    (void)context;
    if (!length || length >= ARRAYSIZE(systemPath)
        || FAILED(StringCchCatW(systemPath, ARRAYSIZE(systemPath), L"\\dinput8.dll")))
        return TRUE;

    systemDinput = LoadLibraryExW(systemPath, NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (systemDinput) {
        systemDirectInput8Create = (DirectInput8CreateFn)(void *)GetProcAddress(systemDinput, "DirectInput8Create");
        if (systemDirectInput8Create == SpotlightDirectInput8Create)
            systemDirectInput8Create = NULL;
    }
    return TRUE;
}

HRESULT WINAPI SpotlightDirectInput8Create(HINSTANCE instance, DWORD version, const IID *interfaceId,
                                           LPVOID *output, LPUNKNOWN outer)
{
    /* This exported call runs after Windows releases the DLL loader lock. */
    InitOnceExecuteOnce(&initialized, initialize, NULL, NULL);
    if (!systemDirectInput8Create)
        return E_FAIL;
    return systemDirectInput8Create(instance, version, interfaceId, output, outer);
}
