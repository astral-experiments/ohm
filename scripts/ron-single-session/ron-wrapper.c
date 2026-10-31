/* Identical executable in both arms. Only the real registry Ron check can change. */
#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 2) return 100;
    int ron = 0, output = 0, check = 0, source = 0, incremental = 0;
    const char suffix[] = "/ron-0.12.0/src/lib.rs";
    for (int i = 2; i < argc; ++i) {
        size_t n = strlen(argv[i]);
        if (!strcmp(argv[i], "--crate-name") && i + 1 < argc) ron = !strcmp(argv[i + 1], "ron");
        if (!strcmp(argv[i], "--out-dir")) output++;
        if (!strcmp(argv[i], "--emit=dep-info,metadata")) check++;
        if (n >= sizeof(suffix)-1 && !strcmp(argv[i]+n-(sizeof(suffix)-1), suffix)) source++;
        if (strstr(argv[i], "incremental=")) incremental++;
    }
    if (!ron || !output) { execvp(argv[1], argv+1); perror("exec rustc"); return 102; }
    if (check != 1 || source != 1 || output != 1 || incremental) return 103;
    const char *settings = getenv("RON_STUDY_POLICY");
    char mode[16], session[4096], profile[4096];
    FILE *file = settings ? fopen(settings, "r") : NULL;
    if (!file || fscanf(file, "%15s %4095s %4095s", mode, session, profile) != 3 || fclose(file)) return 104;
    char **args = calloc((size_t)argc + 4, sizeof(*args));
    if (!args) return 105;
    size_t added = argc - 1;
    memcpy(args, argv + 1, added * sizeof(*args));
    if (!strcmp(mode, "session")) {
        if (*session != '/' || asprintf(&args[added++], "-Cincremental=%s", session) < 0) return 106;
    } else if (strcmp(mode, "sham")) return 107;
    if (strcmp(profile, "none")) {
        if (*profile != '/' || asprintf(&args[added++], "-Zself-profile=%s", profile) < 0) return 108;
        args[added++] = "-Zself-profile-events=generic-activity,function-args,incr-cache-load";
    }
    execvp(args[0], args); perror("exec Ron rustc"); return 109;
}
