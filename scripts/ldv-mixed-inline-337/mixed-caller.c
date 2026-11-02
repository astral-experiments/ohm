#include <stdio.h>

int line_inline(int x, int condition);
int full_branch(int x, int condition);
int pure_line(int x);

int opaque(int x) { return x ^ 35; }

int main(void) {
    for (int x = 5; x < 38; ++x) {
        for (int c = 0; c <= 1; ++c) {
            int a = x + 17;
            int b = x + 19;
            if (line_inline(x, c) != opaque(c ? 13 * a : a) + a ||
                full_branch(x, c) != opaque(c ? 13 * b : b) + b ||
                pure_line(x) != x + 3) {
                return 1;
            }
        }
    }
    puts("66 mixed-debug calls matched the independent integer oracle");
    return 0;
}
