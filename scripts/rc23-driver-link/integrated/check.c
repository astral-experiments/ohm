#include <assert.h>
#include <dlfcn.h>
#include <stdio.h>
typedef unsigned (*function)(void);
static unsigned from_slot(void *image, const char *name) {
    function *slot = dlsym(image, name);
    assert(slot);
    return (*slot)();
}
int main(int argc, char **argv) {
    assert(argc == 4);
    void *image = dlopen(argv[1], RTLD_NOW | RTLD_GLOBAL);
    if (!image) {
        fprintf(stderr, "%s\n", dlerror());
        return 1;
    }
    function driver = dlsym(RTLD_DEFAULT, argv[2]);
    function hook = dlsym(RTLD_DEFAULT, "hook_value");
    function support = dlsym(RTLD_DEFAULT, argv[3]);
    assert(driver && hook && support);
    printf("%u %u %u %u %u %u\n", from_slot(image, "DRIVER_SLOT"), from_slot(image, "HOOK_SLOT"),
           from_slot(image, "SUPPORT_SLOT"), driver(), hook(), support());
    return 0;
}
