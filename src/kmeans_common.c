/* kmeans_common.c - Implementação das funções compartilhadas. */
#define _POSIX_C_SOURCE 200809L

#include "kmeans_common.h"
#include "rapl.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <time.h>
#endif

#define MAX_THREADS 1024
#define MAX_K 1000000

static void print_usage(const char *prog)
{
    fprintf(stderr,
            "Uso: %s <dados.bin> <centroides.bin> [--threads T] [--max-iter 50]\n"
            "          [--eps 1e-6] [--out-centroids arquivo.bin] [--rapl]\n",
            prog);
}

static int parse_int(const char *s, int min, int max, int *out)
{
    char *end;
    errno = 0;
    long v = strtol(s, &end, 10);
    if (errno != 0 || end == s || *end != '\0' || v < min || v > max)
        return -1;
    *out = (int)v;
    return 0;
}

static int parse_double(const char *s, double *out)
{
    char *end;
    errno = 0;
    double v = strtod(s, &end);
    if (errno != 0 || end == s || *end != '\0' || !(v >= 0.0))
        return -1;
    *out = v;
    return 0;
}

int parse_args(int argc, char **argv, KMeansArgs *args)
{
    args->data_path = NULL;
    args->centroids_path = NULL;
    args->out_centroids_path = NULL;
    args->threads = 1;
    args->max_iter = 50;
    args->eps = 1e-6;
    args->rapl = 0;

    int positional = 0;
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        int has_value = (i + 1 < argc);
        int ok = 0;

        if (strcmp(a, "--threads") == 0 && has_value) {
            ok = parse_int(argv[++i], 1, MAX_THREADS, &args->threads) == 0;
        } else if (strcmp(a, "--max-iter") == 0 && has_value) {
            ok = parse_int(argv[++i], 1, 1000000, &args->max_iter) == 0;
        } else if (strcmp(a, "--eps") == 0 && has_value) {
            ok = parse_double(argv[++i], &args->eps) == 0;
        } else if (strcmp(a, "--out-centroids") == 0 && has_value) {
            args->out_centroids_path = argv[++i];
            ok = 1;
        } else if (strcmp(a, "--rapl") == 0) {
            args->rapl = 1;
            ok = 1;
        } else if (strncmp(a, "--", 2) != 0 && positional < 2) {
            if (positional == 0)
                args->data_path = a;
            else
                args->centroids_path = a;
            positional++;
            ok = 1;
        }

        if (!ok) {
            fprintf(stderr, "Erro: argumento invalido ou sem valor: %s\n", a);
            print_usage(argv[0]);
            return -1;
        }
    }

    if (positional != 2) {
        print_usage(argv[0]);
        return -1;
    }
    return 0;
}

double *read_array(const char *path, int64_t *count)
{
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "Erro: nao foi possivel abrir '%s'\n", path);
        return NULL;
    }

    int64_t n = 0;
    double *values = NULL;

    if (fread(&n, sizeof n, 1, f) != 1 || n <= 0 ||
        (uint64_t)n > (uint64_t)(SIZE_MAX / sizeof(double))) {
        fprintf(stderr, "Erro: cabecalho invalido em '%s'\n", path);
        goto fail;
    }

    values = malloc((size_t)n * sizeof(double));
    if (!values) {
        fprintf(stderr, "Erro: memoria insuficiente para %lld valores\n", (long long)n);
        goto fail;
    }

    /* Exige exatamente n valores e nenhum byte sobrando. */
    if (fread(values, sizeof(double), (size_t)n, f) != (size_t)n || fgetc(f) != EOF) {
        fprintf(stderr, "Erro: tamanho do arquivo '%s' nao confere com o cabecalho\n", path);
        goto fail;
    }

    fclose(f);
    *count = n;
    return values;

fail:
    free(values);
    fclose(f);
    return NULL;
}

int write_array(const char *path, const double *values, int64_t count)
{
    FILE *f = fopen(path, "wb");
    if (!f) {
        fprintf(stderr, "Erro: nao foi possivel criar '%s'\n", path);
        return -1;
    }
    int ok = fwrite(&count, sizeof count, 1, f) == 1 &&
             fwrite(values, sizeof(double), (size_t)count, f) == (size_t)count;
    if (fclose(f) != 0)
        ok = 0;
    if (!ok)
        fprintf(stderr, "Erro: falha ao gravar '%s'\n", path);
    return ok ? 0 : -1;
}

int load_inputs(const KMeansArgs *args, double **x, int64_t *n, double **c, int *k)
{
    int64_t kk = 0;
    *x = read_array(args->data_path, n);
    if (!*x)
        return -1;
    *c = read_array(args->centroids_path, &kk);
    if (!*c) {
        free(*x);
        return -1;
    }
    if (kk > MAX_K) {
        fprintf(stderr, "Erro: K=%lld muito grande\n", (long long)kk);
        free(*x);
        free(*c);
        return -1;
    }
    *k = (int)kk;
    return 0;
}

double wall_time(void)
{
#ifdef _WIN32
    static LARGE_INTEGER freq = {0};
    LARGE_INTEGER now;
    if (freq.QuadPart == 0)
        QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&now);
    return (double)now.QuadPart / (double)freq.QuadPart;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
#endif
}

int measure_begin(const KMeansArgs *args, Measure *m)
{
    memset(m, 0, sizeof *m);
    /* Com --rapl, a falha é fatal: melhor abortar do que gravar energia errada. */
    if (args->rapl && rapl_begin() != 0) {
        fprintf(stderr, "Erro: RAPL indisponivel (Intel Power Gadget instalado?)\n");
        return -1;
    }
    m->t0 = wall_time();
    return 0;
}

int measure_end(const KMeansArgs *args, Measure *m)
{
    m->elapsed_s = wall_time() - m->t0;
    if (args->rapl && rapl_end(&m->energy_j, &m->interval_s) != 0) {
        fprintf(stderr, "Erro: falha na leitura final do RAPL\n");
        return -1;
    }
    return 0;
}

void assign_range(const double *x, int64_t begin, int64_t end,
                  const double *c, int k,
                  double *sum, int64_t *cnt, double *sse)
{
    double local_sse = 0.0;
    for (int64_t i = begin; i < end; i++) {
        double d2;
        int j = nearest_centroid(x[i], c, k, &d2);
        sum[j] += x[i];
        cnt[j] += 1;
        local_sse += d2;
    }
    *sse += local_sse;
}

double update_centroids(double *c, const double *sum, const int64_t *cnt, int k)
{
    double max_shift = 0.0;
    for (int j = 0; j < k; j++) {
        if (cnt[j] == 0)
            continue; /* cluster vazio: mantém o centróide anterior */
        double novo = sum[j] / (double)cnt[j];
        double shift = novo - c[j];
        if (shift < 0)
            shift = -shift;
        if (shift > max_shift)
            max_shift = shift;
        c[j] = novo;
    }
    return max_shift;
}

int report_result(const KMeansArgs *args, const Measure *m, int iters, double sse,
                  const double *c, int k)
{
    printf("RESULT time_s=%.9f iters=%d sse=%.17g\n", m->elapsed_s, iters, sse);
    if (args->rapl)
        printf("ENERGY energy_j=%.6f interval_s=%.6f\n", m->energy_j, m->interval_s);
    printf("CENTROIDS");
    for (int j = 0; j < k; j++)
        printf(" %.17g", c[j]);
    printf("\n");
    fflush(stdout);

    if (args->out_centroids_path && write_array(args->out_centroids_path, c, k) != 0)
        return 1;
    return 0;
}
