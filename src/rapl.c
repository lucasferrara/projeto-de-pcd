/* rapl.c - Ver rapl.h. */
#include "rapl.h"

#ifdef _WIN32

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
#include <windows.h>

#define DEFAULT_DLL "C:\\Program Files\\Intel\\Power Gadget 3.6\\EnergyLib64.dll"

/* API da EnergyLib (Intel Power Gadget 3.x). */
typedef bool (*InitFn)(void);
typedef bool (*GetNumMsrsFn)(int *);
typedef bool (*GetMsrNameFn)(int, wchar_t *);
typedef bool (*GetMsrFuncFn)(int, int *);
typedef bool (*ReadSampleFn)(void);
typedef bool (*GetPowerDataFn)(int, int, double *, int *);
typedef bool (*GetTimeIntervalFn)(double *);

static ReadSampleFn read_sample;
static GetPowerDataFn get_power_data;
static GetTimeIntervalFn get_time_interval;
static int pkg_msr = -1; /* índice do MSR "Processor" = energia do pacote */

/* GetProcAddress devolve FARPROC; passar por void* evita o aviso
   -Wcast-function-type ao converter para o tipo real da função. */
static void *sym(HMODULE h, const char *name)
{
    void *p = (void *)GetProcAddress(h, name);
    if (!p)
        fprintf(stderr, "RAPL: simbolo %s ausente na EnergyLib\n", name);
    return p;
}

int rapl_begin(void)
{
    const char *path = getenv("ENERGYLIB_PATH");
    if (!path || !*path)
        path = DEFAULT_DLL;

    /* ALTERED_SEARCH_PATH: as DLLs de que ela depende são buscadas na pasta dela. */
    HMODULE h = LoadLibraryExA(path, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!h) {
        fprintf(stderr, "RAPL: nao foi possivel carregar %s\n", path);
        return -1;
    }

    InitFn init = (InitFn)sym(h, "IntelEnergyLibInitialize");
    GetNumMsrsFn get_num_msrs = (GetNumMsrsFn)sym(h, "GetNumMsrs");
    GetMsrNameFn get_msr_name = (GetMsrNameFn)sym(h, "GetMsrName");
    GetMsrFuncFn get_msr_func = (GetMsrFuncFn)sym(h, "GetMsrFunc");
    read_sample = (ReadSampleFn)sym(h, "ReadSample");
    get_power_data = (GetPowerDataFn)sym(h, "GetPowerData");
    get_time_interval = (GetTimeIntervalFn)sym(h, "GetTimeInterval");
    if (!init || !get_num_msrs || !get_msr_name || !get_msr_func ||
        !read_sample || !get_power_data || !get_time_interval)
        return -1;

    if (!init()) {
        fprintf(stderr, "RAPL: IntelEnergyLibInitialize falhou (driver carregado?)\n");
        return -1;
    }

    /* Procura o MSR de energia (func 1 = MSR_FUNC_POWER) chamado "Processor",
       que corresponde ao domínio PKG (pacote inteiro da CPU). */
    int n = 0;
    get_num_msrs(&n);
    for (int i = 0; i < n; i++) {
        wchar_t name[256] = {0};
        int func = -1;
        get_msr_name(i, name);
        get_msr_func(i, &func);
        if (func == 1 && wcscmp(name, L"Processor") == 0)
            pkg_msr = i;
    }
    if (pkg_msr < 0) {
        fprintf(stderr, "RAPL: MSR de energia do pacote nao encontrado\n");
        return -1;
    }

    /* Amostra de referência: a próxima ReadSample mede a partir daqui. */
    return read_sample() ? 0 : -1;
}

int rapl_end(double *energy_j, double *interval_s)
{
    double data[3] = {0};
    int count = 0;
    if (pkg_msr < 0 || !read_sample())
        return -1;
    /* data = {potência média (W), energia no intervalo (J), energia (mWh)} */
    if (!get_power_data(0, pkg_msr, data, &count) || count < 2)
        return -1;
    if (!get_time_interval(interval_s))
        return -1;
    *energy_j = data[1];
    return 0;
}

#else /* !_WIN32 */

#include <stdio.h>

int rapl_begin(void)
{
    fprintf(stderr, "RAPL: suportado apenas no Windows (Intel Power Gadget)\n");
    return -1;
}

int rapl_end(double *energy_j, double *interval_s)
{
    (void)energy_j;
    (void)interval_s;
    return -1;
}

#endif
