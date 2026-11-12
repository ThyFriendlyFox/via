CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -O2 -D_DEFAULT_SOURCE
SRC := src/zone.c src/line.c src/dtmf.c src/contactid.c

.PHONY: test clean

test: build/test_herald
	./build/test_herald

build/test_herald: $(SRC) $(wildcard src/*.h) tests/test_herald.c
	mkdir -p build
	$(CC) $(CFLAGS) -Isrc $(SRC) tests/test_herald.c -lm -o $@

clean:
	rm -rf build
