/*
 * kmeans_omp.c - K-Means 1D paralelo com OpenMP.
 *
 * Mesmo algoritmo da versão sequencial; só o passo de atribuição é paralelo,
 * usando redução de arrays (OpenMP >= 4.5) para sum[], cnt[] e sse.
 */
#include "kmeans_common.h"

#include <omp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

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

    double *sum = malloc((size_t)k * sizeof *sum);
    int64_t *cnt = malloc((size_t)k * sizeof *cnt);
    if (!sum || !cnt) {
        fprintf(stderr, "Erro: memoria insuficiente\n");
        return 1;
    }

    omp_set_dynamic(0); /* usa exatamente o número de threads pedido */
    omp_set_num_threads(args.threads);

    Measure m;
    if (measure_begin(&args, &m) != 0)
        return 1;
    int iters = 0;
    double sse = 0.0;

    while (iters < args.max_iter) {
        memset(sum, 0, (size_t)k * sizeof *sum);
        memset(cnt, 0, (size_t)k * sizeof *cnt);
        sse = 0.0;

        /* Atribuição paralela: cada thread acumula cópias privadas, somadas no fim. */
#pragma omp parallel for schedule(static) reduction(+ : sum[:k], cnt[:k], sse)
        for (int64_t i = 0; i < n; i++) {
            double d2;
            int j = nearest_centroid(x[i], c, k, &d2);
            sum[j] += x[i];
            cnt[j] += 1;
            sse += d2;
        }
        iters++;

        if (update_centroids(c, sum, cnt, k) < args.eps)
            break;
    }

    if (measure_end(&args, &m) != 0)
        return 1;
    int rc = report_result(&args, &m, iters, sse, c, k);

    free(sum);
    free(cnt);
    free(x);
    free(c);
    return rc;
}
