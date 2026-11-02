#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>

extern const unsigned char *conflict_message(bool);
extern size_t conflict_message_len(bool);

int main(void) {
    for (int i = 0; i < 2; i++) {
        size_t len = conflict_message_len(i != 0);
        if (len == 0 || len > 1024 ||
            fwrite(conflict_message(i != 0), 1, len, stdout) != len ||
            putchar('\n') == EOF) {
            return 1;
        }
    }
    return 0;
}
