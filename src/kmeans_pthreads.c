/*
 * kmeans_pthreads.c - K-Means 1D paralelo com Pthreads.
 *
 * Mesmo algoritmo da versão sequencial. Em cada iteração:
 *   1. cria T threads; cada uma processa um bloco contíguo de pontos e
 *      acumula somas/contagens/SSE em buffers PRÓPRIOS (sem locks);
 *   2. join; a thread principal reduz os buffers e atualiza os centróides.
 */
#include "kmeans_common.h"

#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    const double *x;
    const double *c;
    int64_t begin, end; /* bloco [begin, end) desta thread */
    int k;
    double *sum;        /* acumuladores locais (k posições) */
    int64_t *cnt;
    double sse;
} Task;

static void *worker(void *arg)
{
    Task *t = arg;
    memset(t->sum, 0, (size_t)t->k * sizeof *t->sum);
    memset(t->cnt, 0, (size_t)t->k * sizeof *t->cnt);
    t->sse = 0.0;
    assign_range(t->x, t->begin, t->end, t->c, t->k, t->sum, t->cnt, &t->sse);
    return NULL;
}

int main(int argc, char **argv)
{
    KMeansArgs args;
    if (parse_args(argc, argv, &args) != 0)
        return 2;

    double *x, *c;
    int64_t n;
    int k;
    if (load_inputs(&args, &x, &n, &c, &k) != 0)
        return 1;

    int T = args.threads;
    /* Cada thread tem seu bloco de acumuladores, separado do vizinho por 512 B
       (64 valores) para evitar FALSE SHARING. Só uma linha de cache (64 B) não
       basta: o prefetcher da Intel traz pares de linhas (128 B), e com folga
       pequena esta versão ficava ~2x mais lenta que a OpenMP com 6 threads. */
    size_t stride = (size_t)k + 64;
    double *sum = malloc((size_t)k * sizeof *sum);
    int64_t *cnt = malloc((size_t)k * sizeof *cnt);
    double *local_sum = malloc((size_t)T * stride * sizeof *local_sum);
    int64_t *local_cnt = malloc((size_t)T * stride * sizeof *local_cnt);
    Task *tasks = malloc((size_t)T * sizeof *tasks);
    pthread_t *tids = malloc((size_t)T * sizeof *tids);
    if (!sum || !cnt || !local_sum || !local_cnt || !tasks || !tids) {
        fprintf(stderr, "Erro: memoria insuficiente\n");
        return 1;
    }

    /* Divisão em blocos: thread t fica com [n*t/T, n*(t+1)/T).
       Funciona com n não divisível por T e com T > n (blocos vazios). */
    for (int t = 0; t < T; t++) {
        tasks[t].x = x;
        tasks[t].c = c;
        tasks[t].begin = n * t / T;
        tasks[t].end = n * (t + 1) / T;
        tasks[t].k = k;
        tasks[t].sum = local_sum + (size_t)t * stride;
        tasks[t].cnt = local_cnt + (size_t)t * stride;
    }

    Measure m;
    if (measure_begin(&args, &m) != 0)
        return 1;
    int iters = 0;
    double sse = 0.0;

    while (iters < args.max_iter) {
        for (int t = 0; t < T; t++) {
            if (pthread_create(&tids[t], NULL, worker, &tasks[t]) != 0) {
                fprintf(stderr, "Erro: pthread_create falhou\n");
                return 1;
            }
        }
        for (int t = 0; t < T; t++)
            pthread_join(tids[t], NULL);

        /* Redução (em ordem fixa de threads). */
        memset(sum, 0, (size_t)k * sizeof *sum);
        memset(cnt, 0, (size_t)k * sizeof *cnt);
        sse = 0.0;
        for (int t = 0; t < T; t++) {
            for (int j = 0; j < k; j++) {
                sum[j] += tasks[t].sum[j];
                cnt[j] += tasks[t].cnt[j];
            }
            sse += tasks[t].sse;
        }
        iters++;

        if (update_centroids(c, sum, cnt, k) < args.eps)
            break;
    }

    if (measure_end(&args, &m) != 0)
        return 1;
    int rc = report_result(&args, &m, iters, sse, c, k);

    free(tids);
    free(tasks);
    free(local_cnt);
    free(local_sum);
    free(sum);
    free(cnt);
    free(x);
    free(c);
    return rc;
}
