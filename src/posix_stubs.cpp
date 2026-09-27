#include <cstddef>
#include <sys/types.h>

extern "C" {

int symlink(const char*, const char*) { return -1; }
int chdir(const char*) { return -1; }
int truncate(const char*, off_t) { return -1; }
int mkdir(const char*, mode_t) { return -1; }
int fchmodat(int, const char*, mode_t, int) { return -1; }
ssize_t readlink(const char*, char*, size_t) { return -1; }
long pathconf(const char*, int) { return 1024; }
char* getcwd(char* buf, size_t size) {
    if (buf && size > 1) { buf[0] = '/'; buf[1] = '\0'; return buf; }
    return nullptr;
}
int fchmod(int, mode_t) { return -1; }

ssize_t write(int, const void*, size_t count) { return count; }
ssize_t read(int, void*, size_t) { return 0; }
void __bcc_con_outbyte(int) {}

}
