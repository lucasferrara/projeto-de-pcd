# Makefile - K-Means 1D (sequencial, Pthreads, OpenMP)
# Uso (terminal MSYS2 UCRT64 ou Linux):  make  |  make clean
# No PowerShell, os scripts Python compilam sozinhos (scripts/build.py, mesmas flags).

CC     = gcc
CFLAGS = -O2 -std=c11 -Wall
BIN    = bin

ifeq ($(OS),Windows_NT)
  EXE = .exe
endif

COMMON_SRC = src/kmeans_common.c src/rapl.c
COMMON_DEP = $(COMMON_SRC) src/kmeans_common.h src/rapl.h

TARGETS = $(BIN)/kmeans_seq$(EXE) $(BIN)/kmeans_pthreads$(EXE) $(BIN)/kmeans_omp$(EXE)

all: $(TARGETS)

$(BIN)/kmeans_seq$(EXE): src/kmeans_seq.c $(COMMON_DEP) | $(BIN)
	$(CC) $(CFLAGS) -o $@ src/kmeans_seq.c $(COMMON_SRC) $(LDFLAGS)

$(BIN)/kmeans_pthreads$(EXE): src/kmeans_pthreads.c $(COMMON_DEP) | $(BIN)
	$(CC) $(CFLAGS) -pthread -o $@ src/kmeans_pthreads.c $(COMMON_SRC) $(LDFLAGS)

$(BIN)/kmeans_omp$(EXE): src/kmeans_omp.c $(COMMON_DEP) | $(BIN)
	$(CC) $(CFLAGS) -fopenmp -o $@ src/kmeans_omp.c $(COMMON_SRC) $(LDFLAGS)

$(BIN):
	mkdir -p $(BIN)

clean:
	rm -rf $(BIN)

.PHONY: all clean
