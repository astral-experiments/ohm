/* The stopped rustc's executable mappings bind an ordinary bin/rustc to its actual driver. */
static void driver_at_exit(const struct task *t) {
    char proc[80], path[4096], name[4096];
    if (t->tid != t->group) return;
    output(proc, sizeof(proc), "/proc/%d/exe", t->tid);
    ssize_t n = readlink(proc, path, sizeof(path) - 1);
    if (n < 0 && errno == ENOENT) return;
    require(n > 0 && (size_t)n < sizeof(path) - 1, "exiting executable");
    path[n] = 0;
    const char *base = strrchr(path, '/');
    if (!base || strcmp(base, "/rustc") != 0) return;
    output(proc, sizeof(proc), "/proc/%d/maps", t->tid);
    FILE *input = fopen(proc, "r");
    int used = snprintf(name, sizeof(name), "%s/%05d.maps", directory, t->image);
    require(input != NULL && used > 0 && (size_t)used < sizeof(name), "exiting rustc maps");
    FILE *out = fopen(name, "wx");
    require(out != NULL, "new maps record");
    char *line = NULL;
    size_t capacity = 0;
    while (getline(&line, &capacity, input) >= 0) {
        if (strstr(line, "librustc_driver-") || strstr(line, "/libLLVM"))
            require(fputs(line, out) >= 0, "write mapping");
    }
    free(line);
    require(!ferror(input) && fclose(input) == 0 && fclose(out) == 0, "complete mappings");
}
