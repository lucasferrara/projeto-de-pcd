/*
 * rapl.h - Leitura de energia da CPU (RAPL) em volta de um trecho de código.
 *
 * Windows: usa a EnergyLib64.dll do Intel Power Gadget 3.6, carregada em tempo
 * de execução (LoadLibrary), então os executáveis não dependem dela para
 * compilar nem para rodar sem a opção --rapl.
 * Outros sistemas: indisponível (rapl_begin retorna erro).
 */
#ifndef RAPL_H
#define RAPL_H

/* Inicia a medição. Retorna 0 se o RAPL está disponível, != 0 caso contrário. */
int rapl_begin(void);

/* Encerra a medição: energia do pacote da CPU (J) e duração do intervalo (s). */
int rapl_end(double *energy_j, double *interval_s);

#endif
