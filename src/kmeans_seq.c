/* kmeans_seq.c - K-Means 1D sequencial (linha de base para o speedup). */
#include "kmeans_common.h"

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

    Measure m;
    if (measure_begin(&args, &m) != 0)
        return 1;
    int iters = 0;
    double sse = 0.0;

    while (iters < args.max_iter) {
        memset(sum, 0, (size_t)k * sizeof *sum);
        memset(cnt, 0, (size_t)k * sizeof *cnt);
        sse = 0.0;

        assign_range(x, 0, n, c, k, sum, cnt, &sse); /* atribuição */
        iters++;

        if (update_centroids(c, sum, cnt, k) < args.eps) /* atualização */
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
