#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <openssl/evp.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <unistd.h>

/* The caller supplies a NUL-delimited manifest from the actual linker argv. */
int main(int argc, char **argv) {
    if (argc != 3) return 2;
    int retain = strcmp(argv[1], "lease") == 0;
    if (!retain && strcmp(argv[1], "read") != 0) return 2;
    FILE *input = fopen(argv[2], "rb");
    EVP_MD_CTX *hash = EVP_MD_CTX_new();
    unsigned char *buffer = malloc(256 * 1024);
    struct rlimit limit;
    if (!input || !hash || !buffer || getrlimit(RLIMIT_NOFILE, &limit)) return 3;
    sigset_t events;
    sigemptyset(&events);
    sigaddset(&events, SIGIO);
    if (sigprocmask(SIG_BLOCK, &events, NULL)) return 3;
    int *held = NULL;
    size_t held_count = 0, capacity = 0, count = 0;
    char *name = NULL;
    size_t name_length = 0;
    ssize_t field;
    while ((field = getdelim(&name, &name_length, 0, input)) >= 0) {
        if (field < 2 || name[0] != '/' || name[field - 1] != 0) return 4;
        int fd = open(name, O_RDONLY | O_CLOEXEC | O_NONBLOCK);
        struct stat before, after;
        if (fd < 0 || fstat(fd, &before) || !S_ISREG(before.st_mode)) {
            fprintf(stderr, "cannot open input %zu: %s\n", count, strerror(errno));
            return 5;
        }
        int lease_error = -1;
        if (retain) {
            lease_error = 0;
            if (fcntl(fd, F_SETLEASE, F_RDLCK) < 0) lease_error = errno;
        }
        if (EVP_DigestInit_ex(hash, EVP_sha256(), NULL) != 1) return 6;
        uint64_t bytes = 0;
        ssize_t size;
        while ((size = read(fd, buffer, 256 * 1024)) > 0) {
            if (EVP_DigestUpdate(hash, buffer, (size_t)size) != 1) return 6;
            bytes += (uint64_t)size;
        }
        unsigned char digest[EVP_MAX_MD_SIZE];
        unsigned int digest_size;
        if (size < 0 || EVP_DigestFinal_ex(hash, digest, &digest_size) != 1 || digest_size != 32) return 6;
        if (fstat(fd, &after) || bytes != (uint64_t)before.st_size ||
            after.st_size != before.st_size || after.st_ctim.tv_sec != before.st_ctim.tv_sec ||
            after.st_ctim.tv_nsec != before.st_ctim.tv_nsec) return 7;
        printf("%zu %" PRIu64 " %d %" PRIuMAX " %" PRIuMAX " ", count, bytes, lease_error,
               (uintmax_t)after.st_dev, (uintmax_t)after.st_ino);
        for (unsigned i = 0; i != digest_size; ++i) printf("%02x", digest[i]);
        putchar('\n');
        if (retain && !lease_error) {
            if (held_count == capacity) {
                capacity = capacity ? 2 * capacity : 256;
                int *fds = reallocarray(held, capacity, sizeof(*held));
                if (!fds) return 8;
                held = fds;
            }
            held[held_count++] = fd;
        } else if (close(fd)) return 9;
        ++count;
    }
    if (ferror(input) || fclose(input)) return 9;
    size_t lost = 0;
    for (size_t i = 0; i < held_count; ++i) {
        if (fcntl(held[i], F_GETLEASE) != F_RDLCK) ++lost;
        if (close(held[i])) return 9;
    }
    fprintf(stderr, "files=%zu leased=%zu broken=%zu rlimit=%" PRIuMAX "\n",
            count, held_count, lost, (uintmax_t)limit.rlim_cur);
    free(held);
    free(name);
    free(buffer);
    EVP_MD_CTX_free(hash);
    return fflush(stdout) == 0 ? 0 : 9;
}
