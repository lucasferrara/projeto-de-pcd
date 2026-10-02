/*
 * kmeans_common.h - Funções compartilhadas pelas 3 versões do K-Means 1D.
 *
 * Formato dos arquivos binários (little-endian):
 *   int64 count  seguido de  count valores double
 *   - dataset:    count = N pontos
 *   - centróides: count = K centróides iniciais
 */
#ifndef KMEANS_COMMON_H
#define KMEANS_COMMON_H

#include <stdint.h>

typedef struct {
    const char *data_path;          /* arquivo de pontos */
    const char *centroids_path;     /* arquivo de centróides iniciais */
    const char *out_centroids_path; /* --out-centroids (opcional, NULL se ausente) */
    int threads;                    /* --threads  (ignorado na versão sequencial) */
    int max_iter;                   /* --max-iter */
    double eps;                     /* --eps: critério de parada no deslocamento */
    int rapl;                       /* --rapl: mede a energia do laço via RAPL */
} KMeansArgs;

/* Medição do laço principal: tempo de parede e, com --rapl, energia da CPU. */
typedef struct {
    double t0;
    double elapsed_s;
    double energy_j;   /* energia do pacote da CPU no laço (só com --rapl) */
    double interval_s; /* duração do intervalo medido pelo RAPL */
} Measure;

/* Lê a linha de comando. Retorna 0 em sucesso, != 0 em erro (já imprime uso). */
int parse_args(int argc, char **argv, KMeansArgs *args);

/* Lê pontos e centróides. Retorna 0 em sucesso; aloca *x e *c (liberar com free). */
int load_inputs(const KMeansArgs *args, double **x, int64_t *n, double **c, int *k);

/* Lê/grava um vetor no formato binário descrito acima. */
double *read_array(const char *path, int64_t *count);
int write_array(const char *path, const double *values, int64_t count);

/* Relógio de parede em segundos (alta resolução). */
double wall_time(void);

/* Início/fim da medição (tempo e, se pedido, energia). Retornam 0 em sucesso. */
int measure_begin(const KMeansArgs *args, Measure *m);
int measure_end(const KMeansArgs *args, Measure *m);

/* Índice do centróide mais próximo de x; grava a distância ao quadrado em *dist2. */
static inline int nearest_centroid(double x, const double *c, int k, double *dist2)
{
    int best = 0;
    double d = x - c[0];
    double best_d = d * d;
    for (int j = 1; j < k; j++) {
        d = x - c[j];
        d = d * d;
        if (d < best_d) {
            best_d = d;
            best = j;
        }
    }
    *dist2 = best_d;
    return best;
}

/*
 * Passo de atribuição para os pontos x[begin..end): ACUMULA em sum[], cnt[] e *sse.
 * (O chamador zera os acumuladores.)
 */
void assign_range(const double *x, int64_t begin, int64_t end,
                  const double *c, int k,
                  double *sum, int64_t *cnt, double *sse);

/*
 * Passo de atualização: c[j] = sum[j] / cnt[j]. Cluster vazio mantém o centróide.
 * Retorna o maior deslocamento absoluto de um centróide.
 */
double update_centroids(double *c, const double *sum, const int64_t *cnt, int k);

/*
 * Imprime as linhas RESULT, ENERGY (com --rapl) e CENTROIDS e grava
 * --out-centroids se pedido. Retorna o exit code do programa.
 */
int report_result(const KMeansArgs *args, const Measure *m, int iters, double sse,
                  const double *c, int k);

#endif
