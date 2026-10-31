/* Select the frozen receiver and the actual previously observed output paths. */
static char scope_paths[5][PATH_MAX];
static struct stat scope_rust, scope_wild, scope_cc;
static void enroll_scopes(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) fatal("open roles");
    for (int i = 0; i < 5; i++) {
        char *s = scope_paths[i];
        need(fgets(s, PATH_MAX, f) != NULL && s[0] == '/', "invalid enrolled path");
        char *end = strchr(s, '\n');
        need(end && end[1] == 0, "truncated enrolled path");
        *end = 0;
    }
    need(fgetc(f) == EOF && !ferror(f), "unused scope path");
    if (fclose(f) || stat(scope_paths[0], &scope_rust) || stat(scope_paths[1], &scope_wild)
            || stat(scope_paths[4], &scope_cc)) fatal("enrolled SDK or compiler driver");
}
static int e2e_role(const char *exe, const struct stat *actual, const char *buf, size_t size) {
    if (same(actual, &scope_rust)) {
        const char *name = following(buf, size, "--crate-name");
        char recipe[PATH_MAX];
        pathcat(recipe, "%s%s", scope_paths[3], ".rlink");
        if ((name && !strcmp(name, "e2e") && arg(buf, size, "crates/ty_server/tests/e2e/main.rs"))
                || arg(buf, size, recipe)) return 0;
    }
    if (!strcmp(exe, scope_paths[2]) && size == strlen(buf) + 1 && !strcmp(buf, exe)) {
        struct stat output;
        need(!stat(exe, &output) && same(actual, &output), "different executed generator");
        return 1;
    }
    if (same(actual, &scope_cc) || same(actual, &scope_wild)) {
        const char *output = following(buf, size, "-o");
        if (output && !strcmp(output, scope_paths[3])) return same(actual, &scope_cc) ? 2 : 3;
    }
    return -1;
}
