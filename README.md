<h1>Algoritmo K-Means 1D: Pthreads vs. OpenMP</h1>
<p>Projeto de Programação Concorrente e Distribuída - 2026.2.</p>

<p><img src="https://dci.unifesp.br/images/marca_unifesp/Unifesp_simples_policromia_RGB.png" width=48px height=21px /> UNIFESP - <a href="http://lattes.cnpq.br/8685746591566082" target="_blank">Profª. Dra. Denise Stringhini</a></p>

<p>Grupo: Daniel Kruger, Larissa Martins, Lucas Ferrara</p>

## Estrutura

```
src/kmeans_common.h/.c    leitura dos dados, timer, passos de atribuição/atualização
src/rapl.h/.c             leitura de energia RAPL (EnergyLib do Intel Power Gadget)
src/kmeans_seq.c          versão sequencial (linha de base)
src/kmeans_pthreads.c     versão Pthreads (blocos contíguos + somas locais por thread)
src/kmeans_omp.c          versão OpenMP (parallel for + reduction de arrays)
scripts/gen_datasets.py   gera os datasets sintéticos (seed fixa)
scripts/run_benchmarks.py roda tudo e exporta os CSVs
scripts/energy.py         executa um kmeans e coleta tempo/energia (RAPL ou estimativa)
scripts/build.py          compila os executáveis (chamado automaticamente)
tests/                    testes (unittest)
results/                  CSVs da última execução completa
```

As três versões usam o mesmo algoritmo, e só muda o passo de atribuição, que é o paralelizado. A cada iteração, cada ponto vai para o centróide mais próximo e cada centróide recebe a média dos seus pontos. Um cluster vazio mantém o centróide anterior. O algoritmo para quando o maior deslocamento de um centróide fica abaixo de `eps` (1e-6) ou ao chegar em `max-iter` (50). O tempo e a energia medidos cobrem só o laço do K-Means, sem a leitura dos arquivos.

## Instalação (Windows)

1. Instale o [MSYS2](https://www.msys2.org/) e, no terminal **MSYS2 UCRT64**, rode:
   ```
   pacman -S mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-libgomp make
   ```
   O `libgomp` é o runtime do OpenMP e vem em um pacote separado do gcc. Sem ele, o `-fopenmp` falha com `cannot find -lgomp`.
2. Python 3, sem dependências externas. No PowerShell, use `py`.
3. Os scripts encontram o gcc em `C:\msys64\ucrt64\bin` mesmo que ele não esteja no PATH. As DLLs de runtime (libgomp, winpthread) são copiadas para `bin/`, então os executáveis rodam direto do PowerShell.
4. **Energia via RAPL (opcional, recomendado):** instale o Intel Power Gadget 3.6. Ele foi descontinuado pela Intel, mas o instalador ainda é encontrado em espelhos, e funciona no i5-9400F. Os executáveis carregam `C:\Program Files\Intel\Power Gadget 3.6\EnergyLib64.dll`. Se estiver em outro lugar, defina `ENERGYLIB_PATH`. Não é preciso rodar como Administrador.
   - No Windows 11 com "Integridade de Memória" (Isolamento de núcleo) ativa, o driver do Power Gadget pode ser bloqueado. Nesse caso, desative a opção e reinicie.
   - A mensagem `error: failed to initialize MDH_Context` no stderr vem da própria EnergyLib, é inofensiva e não afeta a leitura de energia.
   - O `PowerLog3.0.exe` do pacote não funcionou nesta máquina (`Error: ??`), por isso a energia é lida direto da DLL.

## Como usar

```powershell
py scripts/gen_datasets.py            # gera data/small, medium, large (~90 MB, ~10 s)
py -m unittest discover -s tests -v   # 28 testes
py scripts/run_benchmarks.py --quick  # teste rápido do fluxo (segundos)
py scripts/run_benchmarks.py          # benchmark completo (~7 min)
```

O benchmark completo compila o que faltar e gera os datasets ausentes. Para cada dataset, roda a versão sequencial 10 vezes e depois Pthreads e OpenMP com 1, 2, 4 e 6 threads, 10 vezes cada. Antes de cada cenário há 1 rodada de aquecimento, que é descartada. Opções úteis: `--datasets small,medium`, `--runs 5`, `--threads 1,2,4,6`, `--energy auto|rapl|estimate`.

Datasets (mistura de K gaussianas 1D, seed 2026):

| nome   | N          | K  |
|--------|------------|----|
| small  | 10.000     | 4  |
| medium | 1.000.000  | 8  |
| large  | 10.000.000 | 16 |

Os executáveis também podem ser usados direto:
`bin\kmeans_omp.exe data\medium.bin data\medium_centroids.bin --threads 6 [--max-iter 50] [--eps 1e-6] [--rapl] [--out-centroids f.bin]`

## Resultados

Todos os arquivos ficam em `results/`. Cada execução sobrescreve os anteriores, então renomeie a pasta se quiser guardar uma rodada.

`raw_runs.csv` tem uma linha por rodada e é gravado à medida que o benchmark roda:

| coluna | significado |
|---|---|
| timestamp, dataset, N, K, version, threads, run | identificação da rodada |
| time_s | tempo do laço do K-Means (s) |
| iters, sse | iterações executadas e soma dos erros quadráticos (devem bater entre as versões) |
| energy_j | energia do pacote da CPU durante o laço (J) |
| avg_power_w | energy_j / intervalo medido (W) |
| energy_method | `rapl_energylib` (medido) ou `estimate_tdp` (estimado) |
| speedup | tempo médio sequencial do dataset / time_s |
| efficiency | speedup / threads |

Os outros arquivos:
- `summary.csv`: média, desvio padrão e mediana por (dataset, versão, threads). A coluna `energy_vs_seq` traz a energia média dividida pela energia média da versão sequencial.
- `environment.json`: CPU, sistema operacional, versões do gcc e do Python, plano de energia, potência ociosa do pacote e parâmetros usados.
- `bench_log.txt`: saída do terminal da execução.

## Limitações da medição de energia

- O RAPL mede o **pacote inteiro** da CPU (domínio PKG), incluindo o consumo de outros programas abertos. A potência ociosa registrada no `environment.json` serve de referência.
- O contador RAPL é atualizado a cada ~1 ms. No dataset small, cada execução dura ~2 ms, então a energia medida é dominada por quantização e ruído. Use o medium e o large para comparar energia.
- **Sem o Power Gadget, a energia é uma estimativa e não uma medição:** (65 W de TDP / 6 núcleos) × threads × tempo, com `energy_method=estimate_tdp`.

Dicas para medir: use o plano de energia "Alto desempenho", feche navegador e IDEs e deixe o PC na tomada.
