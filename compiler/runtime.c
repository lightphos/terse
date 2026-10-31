
#if !defined(_WIN32)
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200112L
#endif
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <process.h>
#else
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#endif

#define SQLITE_OK 0
#define SQLITE_ROW 100
#define SQLITE_DONE 101
#define SQLITE_TRANSIENT ((void(*)(void*))-1)

typedef struct sqlite3 sqlite3;
typedef struct sqlite3_stmt sqlite3_stmt;
#ifdef _WIN32
    #define WIN32_LEAN_AND_MEAN
    #include <windows.h>
    static HMODULE terse_sqlite = NULL;
    static int (*sqlite3_initialize)(void) = NULL;
    static int (*sqlite3_open)(const char*, sqlite3**) = NULL;
    static int (*sqlite3_close)(sqlite3*) = NULL;
    static const char* (*sqlite3_errmsg)(sqlite3*) = NULL;
    static int (*sqlite3_prepare_v2)(sqlite3*, const char*, int, sqlite3_stmt**, const char**) = NULL;
    static int (*sqlite3_step)(sqlite3_stmt*) = NULL;
    static int (*sqlite3_finalize)(sqlite3_stmt*) = NULL;
    static int (*sqlite3_bind_int64)(sqlite3_stmt*, int, int64_t) = NULL;
    static int (*sqlite3_bind_text)(sqlite3_stmt*, int, const char*, int, void(*)(void*)) = NULL;
    static int64_t (*sqlite3_column_int64)(sqlite3_stmt*, int) = NULL;
    static int (*sqlite3_column_int)(sqlite3_stmt*, int) = NULL;
    static double (*sqlite3_column_double)(sqlite3_stmt*, int) = NULL;
    static const unsigned char* (*sqlite3_column_text)(sqlite3_stmt*, int) = NULL;
    static int (*sqlite3_column_count)(sqlite3_stmt*) = NULL;
    static int (*sqlite3_changes)(sqlite3*) = NULL;
    static void db_load_sqlite(void) {
        if (terse_sqlite) return;
        terse_sqlite = LoadLibraryA("sqlite3.dll");
        if (!terse_sqlite) { fprintf(stderr, "sqlite3.dll not found\n"); exit(1); }
        #define LOAD_SQLITE(name) name = (void*)GetProcAddress(terse_sqlite, #name)
        LOAD_SQLITE(sqlite3_initialize);
        LOAD_SQLITE(sqlite3_open); LOAD_SQLITE(sqlite3_close);
        LOAD_SQLITE(sqlite3_errmsg); LOAD_SQLITE(sqlite3_prepare_v2);
        LOAD_SQLITE(sqlite3_step); LOAD_SQLITE(sqlite3_finalize);
        LOAD_SQLITE(sqlite3_bind_int64); LOAD_SQLITE(sqlite3_bind_text);
        LOAD_SQLITE(sqlite3_column_int64); LOAD_SQLITE(sqlite3_column_int);
        LOAD_SQLITE(sqlite3_column_double); LOAD_SQLITE(sqlite3_column_text);
        LOAD_SQLITE(sqlite3_column_count);
        LOAD_SQLITE(sqlite3_changes);
        #undef LOAD_SQLITE
    }
#else
    /* DB/sqlite support disabled — stubs so we do not need -lsqlite3 */
    static int sqlite3_open(const char* a, sqlite3** b) { (void)a;(void)b; fprintf(stderr,"db support disabled\n"); exit(1); return 1; }
    static int sqlite3_initialize(void) { return 0; }
    static int sqlite3_close(sqlite3* a) { (void)a; return 0; }
    static const char* sqlite3_errmsg(sqlite3* a) { (void)a; return "db disabled"; }
    static int sqlite3_prepare_v2(sqlite3* a, const char* b, int c, sqlite3_stmt** d, const char** e) { (void)a;(void)b;(void)c;(void)d;(void)e; return 1; }
    static int sqlite3_step(sqlite3_stmt* a) { (void)a; return SQLITE_DONE; }
    static int sqlite3_finalize(sqlite3_stmt* a) { (void)a; return 0; }
    static int sqlite3_bind_int64(sqlite3_stmt* a, int b, int64_t c) { (void)a;(void)b;(void)c; return 0; }
    static int sqlite3_bind_text(sqlite3_stmt* a, int b, const char* c, int d, void(*e)(void*)) { (void)a;(void)b;(void)c;(void)d;(void)e; return 0; }
    static int64_t sqlite3_column_int64(sqlite3_stmt* a, int b) { (void)a;(void)b; return 0; }
    static int sqlite3_column_int(sqlite3_stmt* a, int b) { (void)a;(void)b; return 0; }
    static double sqlite3_column_double(sqlite3_stmt* a, int b) { (void)a;(void)b; return 0; }
    static const unsigned char* sqlite3_column_text(sqlite3_stmt* a, int b) { (void)a;(void)b; return (const unsigned char*)""; }
    static int sqlite3_column_count(sqlite3_stmt* a) { (void)a; return 0; }
    static int sqlite3_changes(sqlite3* a) { (void)a; return 0; }
    static void db_load_sqlite(void) {}
#endif

#ifdef _WIN32
  #define WIN32_LEAN_AND_MEAN
  #include <windows.h>
  #include <winsock2.h>
  #include <ws2tcpip.h>
  typedef SOCKET sock_t;
  #define CLOSESOCK closesocket
  #define SOCK_ERR SOCKET_ERROR
  static void sock_init(void) {
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2,2), &wsa) != 0) { fprintf(stderr, "WSAStartup failed\n"); exit(1); }
  }
  static void sock_fini(void) { WSACleanup(); }
#else
  #include <unistd.h>
  #include <sys/socket.h>
  #include <netinet/in.h>
  #include <arpa/inet.h>
  #include <signal.h>
  typedef int sock_t;
  #define CLOSESOCK close
  #define SOCK_ERR (-1)
  static void sock_init(void) {}
  static void sock_fini(void) {}
#endif

/* --- basic TCP sockets (host surface; HTTP lives in lib/http.te) --- */
static int64_t sock_listen(int64_t port) {
  sock_init();
#ifndef _WIN32
  signal(SIGPIPE, SIG_IGN);
#endif
  sock_t srv = socket(AF_INET, SOCK_STREAM, 0);
  if (srv == (sock_t)SOCK_ERR) { fprintf(stderr, "sock.listen: socket failed\n"); exit(1); }
  int yes = 1;
  setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, (const char*)&yes, sizeof(yes));
  struct sockaddr_in addr;
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons((uint16_t)port);
  if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) == SOCK_ERR) {
    fprintf(stderr, "sock.listen: bind failed on :%lld\n", (long long)port); exit(1);
  }
  if (listen(srv, 64) == SOCK_ERR) {
    fprintf(stderr, "sock.listen: listen failed\n"); exit(1);
  }
  fprintf(stderr, "sock.listen on :%lld\n", (long long)port);
  return (int64_t)(intptr_t)srv;
}
static int64_t sock_accept(int64_t listen_fd) {
  sock_t srv = (sock_t)(intptr_t)listen_fd;
  sock_t cli = accept(srv, NULL, NULL);
  if (cli == (sock_t)SOCK_ERR) return INT64_C(-1);
  return (int64_t)(intptr_t)cli;
}
static char* sock_recv(int64_t fd) {
  sock_t s = (sock_t)(intptr_t)fd;
  /* short timeouts so a stalled client cannot hang the accept loop forever */
#ifdef _WIN32
  DWORD tv = 5000;
  setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));
  setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, (const char*)&tv, sizeof(tv));
#else
  struct timeval tv;
  tv.tv_sec = 5; tv.tv_usec = 0;
  setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));
  setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, (const char*)&tv, sizeof(tv));
#endif
  char buf[65536];
  int n = 0;
  /* read until end of HTTP headers (\r\n\r\n) or buffer full */
  while (n < (int)sizeof(buf) - 1) {
    int got = (int)recv(s, buf + n, sizeof(buf) - 1 - n, 0);
    if (got <= 0) break;
    n += got;
    buf[n] = 0;
    if (strstr(buf, "\r\n\r\n")) break;
  }
  if (n <= 0) { char* e = (char*)malloc(1); e[0]=0; return e; }
  buf[n] = 0;
  char* sep = strstr(buf, "\r\n\r\n");
  int content_length = 0;
  char* cl = strstr(buf, "Content-Length:");
  if (cl) sscanf(cl, "Content-Length: %d", &content_length);
  int header_length = sep ? (int)(sep - buf) + 4 : n;
  while (sep && n < header_length + content_length && n < (int)sizeof(buf) - 1) {
    int got = (int)recv(s, buf + n, sizeof(buf) - 1 - n, 0);
    if (got <= 0) break;
    n += got;
    buf[n] = 0;
  }
  char* out = (char*)malloc((size_t)n + 1);
  memcpy(out, buf, (size_t)n);
  out[n] = 0;
  return out;
}
static int64_t sock_send(int64_t fd, const char* data) {
  sock_t s = (sock_t)(intptr_t)fd;
  if (!data) data = "";
  int n = (int)strlen(data);
  int sent = 0;
  while (sent < n) {
    int k = (int)send(s, data + sent, (size_t)(n - sent), 0);
    if (k <= 0) break;
    sent += k;
  }
  return (int64_t)sent;
}
static int64_t sock_close(int64_t fd) {
  sock_t s = (sock_t)(intptr_t)fd;
#ifdef _WIN32
  shutdown(s, SD_BOTH);
#else
  shutdown(s, SHUT_RDWR);
#endif
  CLOSESOCK(s);
  return INT64_C(0);
}

typedef struct { int64_t *d; int64_t n; } List;

static List list_new(int64_t n) {
  List L; L.n = n; L.d = (int64_t*)malloc(sizeof(int64_t) * (n > 0 ? n : 1));
  return L;
}
static int64_t list_get(List L, int64_t i) {
  if (i < 0 || i >= L.n) {
    fprintf(stderr, "index out of bounds: index %lld len %lld\n",
            (long long)i, (long long)L.n);
    exit(1);
  }
  return L.d[i];
}
static int64_t list_len(List L) { return L.n; }
static List list_push(List L, int64_t value) {
    L.d = (int64_t*)realloc(L.d, sizeof(int64_t) * (size_t)(L.n + 1));
    L.d[L.n++] = value;
    return L;
}
static List list_concat(List a, List b) {
    List out = list_new(0);
    for (int64_t i = 0; i < a.n; i++) out = list_push(out, a.d[i]);
    for (int64_t i = 0; i < b.n; i++) out = list_push(out, b.d[i]);
    return out;
}

/* maps {K:V} — str keys; i64 or str values */
typedef struct { const char** k; int64_t* v; int64_t n; int64_t cap; } Map_str_i64;
typedef struct { const char** k; const char** v; int64_t n; int64_t cap; } Map_str_str;
static Map_str_i64 map_str_i64_new(void) { Map_str_i64 m = {NULL,NULL,0,0}; return m; }
static Map_str_str map_str_str_new(void) { Map_str_str m = {NULL,NULL,0,0}; return m; }
static int64_t map_str_i64_len(Map_str_i64 m) { return m.n; }
static int64_t map_str_str_len(Map_str_str m) { return m.n; }
static int64_t map_str_i64_get(Map_str_i64 m, const char* key) {
  if (!key) key = "";
  for (int64_t i = 0; i < m.n; i++) if (strcmp(m.k[i] ? m.k[i] : "", key) == 0) return m.v[i];
  return INT64_C(0);
}
static const char* map_str_str_get(Map_str_str m, const char* key) {
  if (!key) key = "";
  for (int64_t i = 0; i < m.n; i++) if (strcmp(m.k[i] ? m.k[i] : "", key) == 0) return m.v[i] ? m.v[i] : "";
  return "";
}
static int64_t map_str_i64_has(Map_str_i64 m, const char* key) {
  if (!key) key = "";
  for (int64_t i = 0; i < m.n; i++) if (strcmp(m.k[i] ? m.k[i] : "", key) == 0) return INT64_C(1);
  return INT64_C(0);
}
static int64_t map_str_str_has(Map_str_str m, const char* key) {
  if (!key) key = "";
  for (int64_t i = 0; i < m.n; i++) if (strcmp(m.k[i] ? m.k[i] : "", key) == 0) return INT64_C(1);
  return INT64_C(0);
}
static Map_str_i64 map_str_i64_put(Map_str_i64 m, const char* key, int64_t val) {
  if (!key) key = "";
  for (int64_t i = 0; i < m.n; i++) {
    if (strcmp(m.k[i] ? m.k[i] : "", key) == 0) { m.v[i] = val; return m; }
  }
  if (m.n >= m.cap) {
    m.cap = m.cap ? m.cap * 2 : 8;
    m.k = (const char**)realloc(m.k, sizeof(const char*) * (size_t)m.cap);
    m.v = (int64_t*)realloc(m.v, sizeof(int64_t) * (size_t)m.cap);
  }
  m.k[m.n] = key; m.v[m.n] = val; m.n++; return m;
}
static Map_str_str map_str_str_put(Map_str_str m, const char* key, const char* val) {
  if (!key) key = "";
  if (!val) val = "";
  for (int64_t i = 0; i < m.n; i++) {
    if (strcmp(m.k[i] ? m.k[i] : "", key) == 0) { m.v[i] = val; return m; }
  }
  if (m.n >= m.cap) {
    m.cap = m.cap ? m.cap * 2 : 8;
    m.k = (const char**)realloc(m.k, sizeof(const char*) * (size_t)m.cap);
    m.v = (const char**)realloc(m.v, sizeof(const char*) * (size_t)m.cap);
  }
  m.k[m.n] = key; m.v[m.n] = val; m.n++; return m;
}



typedef struct {
    int kind; /* 0 = integer, 1 = string */
    int64_t integer;
    const char* string;
} DbValue;

static sqlite3* terse_db = NULL;

static void db_fail(const char* operation, int code) {
    fprintf(stderr, "sqlite %s failed (%d)%s%s\n", operation, code,
        terse_db ? ": " : "", terse_db ? sqlite3_errmsg(terse_db) : "");
    exit(1);
}

static void db_bind(sqlite3_stmt* stmt, int index, DbValue value) {
    int code = value.kind == 1
        ? sqlite3_bind_text(stmt, index, value.string, -1, SQLITE_TRANSIENT)
        : sqlite3_bind_int64(stmt, index, value.integer);
    if (code != SQLITE_OK) db_fail("bind", code);
}

static sqlite3_stmt* db_prepare_query(const char* sql, int argc, DbValue* args) {
    sqlite3_stmt* stmt = NULL;
    int code = sqlite3_prepare_v2(terse_db, sql, -1, &stmt, NULL);
    if (code != SQLITE_OK) db_fail("prepare", code);
    for (int i = 0; i < argc; i++) db_bind(stmt, i + 1, args[i]);
    return stmt;
}

static const char* db_copy_text(const unsigned char* value) {
    if (!value) return "";
    size_t n = strlen((const char*)value);
    char* copy = (char*)malloc(n + 1);
    memcpy(copy, value, n + 1);
    return copy;
}

static int64_t db_connect(const char* url) {
    db_load_sqlite();
    int init_code = sqlite3_initialize();
    if (init_code != SQLITE_OK) db_fail("initialize", init_code);
    const char* path = url;
    if (strncmp(url, "sqlite3://", 10) == 0) path = url + 10;
    if (strncmp(path, "file/", 5) == 0) path += 5;
    if (terse_db) sqlite3_close(terse_db);
    int code = sqlite3_open(path, &terse_db);
    if (code != SQLITE_OK) db_fail("open", code);
    return 0;
}

static int64_t db_exec(const char* sql, int argc, DbValue* args) {
    sqlite3_stmt* stmt = NULL;
    int code = sqlite3_prepare_v2(terse_db, sql, -1, &stmt, NULL);
    if (code != SQLITE_OK) db_fail("prepare", code);
    for (int i = 0; i < argc; i++) db_bind(stmt, i + 1, args[i]);
    code = sqlite3_step(stmt);
    if (code != SQLITE_DONE) db_fail("execute", code);
    sqlite3_finalize(stmt);
    return sqlite3_changes(terse_db);
}

static List db_query(const char* sql, int argc, DbValue* args) {
    sqlite3_stmt* stmt = NULL;
    int code = sqlite3_prepare_v2(terse_db, sql, -1, &stmt, NULL);
    if (code != SQLITE_OK) db_fail("prepare", code);
    for (int i = 0; i < argc; i++) db_bind(stmt, i + 1, args[i]);
    List rows = list_new(0);
    while ((code = sqlite3_step(stmt)) == SQLITE_ROW) {
        if (sqlite3_column_count(stmt) == 0) break;
        rows.d = (int64_t*)realloc(rows.d, sizeof(int64_t) * (rows.n + 1));
        rows.d[rows.n++] = sqlite3_column_int64(stmt, 0);
    }
    if (code != SQLITE_DONE) db_fail("query", code);
    sqlite3_finalize(stmt);
    return rows;
}

static char* str_from_i64(int64_t x) {
  char* b = (char*)malloc(32);
  snprintf(b, 32, "%lld", (long long)x);
  return b;
}
static char* str_from_bool(bool v) {
  const char* s = v ? "true" : "false";
  size_t n = strlen(s);
  char* b = (char*)malloc(n + 1);
  memcpy(b, s, n + 1);
  return b;
}
static char* str_concat(const char* a, const char* b) {
  size_t na = strlen(a), nb = strlen(b);
  char* r = (char*)malloc(na + nb + 1);
  memcpy(r, a, na); memcpy(r + na, b, nb); r[na+nb] = 0;
  return r;
}
static int64_t str_len(const char* s) { return (int64_t)strlen(s); }

static char* str_slice(const char* s, int64_t start, int64_t length) {
    int64_t size = str_len(s);
    if (start < 0) start = 0;
    if (start > size) start = size;
    if (length < 0) length = 0;
    if (length > size - start) length = size - start;
    char* result = (char*)malloc((size_t)length + 1);
    if (!result) { fprintf(stderr, "out of memory slicing string\n"); exit(1); }
    memcpy(result, s + start, (size_t)length);
    result[length] = 0;
    return result;
}

/* --- [str] lists --- */
typedef struct { const char **d; int64_t n; int64_t cap; } List_str;
static List_str list_new_str(int64_t n) {
  List_str L = {NULL, 0, n};
  if (n > 0) { L.d = (const char**)calloc((size_t)n, sizeof(const char*)); L.n = n; }
  return L;
}
static List_str list_push_str(List_str L, const char* v) {
  if (L.n >= L.cap) {
    L.cap = L.cap ? L.cap * 2 : 8;
    L.d = (const char**)realloc(L.d, sizeof(const char*) * (size_t)L.cap);
  }
  L.d[L.n++] = v ? v : "";
  return L;
}
static int64_t list_len_str(List_str L) { return L.n; }
static const char* list_get_str(List_str L, int64_t i) {
  if (i < 0 || i >= L.n) {
    fprintf(stderr, "index out of bounds: index %lld len %lld\n",
            (long long)i, (long long)L.n);
    exit(1);
  }
  return L.d[i] ? L.d[i] : "";
}

static List_str list_concat_str(List_str a, List_str b) {
  List_str out = list_new_str(0);
  for (int64_t i = 0; i < a.n; i++) out = list_push_str(out, a.d[i] ? a.d[i] : "");
  for (int64_t i = 0; i < b.n; i++) out = list_push_str(out, b.d[i] ? b.d[i] : "");
  return out;
}

/* Width-accurate numeric lists */
#define TERSE_DECL_LIST(Name, CType) \
typedef struct { CType *d; int64_t n; int64_t cap; } List_##Name; \
static List_##Name list_new_##Name(int64_t n) { \
  List_##Name L = {NULL, 0, n}; \
  if (n > 0) L.d = (CType*)calloc((size_t)n, sizeof(CType)); \
  return L; \
} \
static List_##Name list_push_##Name(List_##Name L, CType v) { \
  if (L.n >= L.cap) { L.cap = L.cap ? L.cap * 2 : 8; L.d = (CType*)realloc(L.d, (size_t)L.cap * sizeof(CType)); } \
  L.d[L.n++] = v; \
  return L; \
} \
static int64_t list_len_##Name(List_##Name L) { return L.n; } \
static CType list_get_##Name(List_##Name L, int64_t i) { \
  if (i < 0 || i >= L.n) { \
    fprintf(stderr, "index out of bounds: index %lld len %lld\n", (long long)i, (long long)L.n); \
    exit(1); } \
  return L.d[i]; \
} \
static List_##Name list_concat_##Name(List_##Name a, List_##Name b) { \
  List_##Name out = list_new_##Name(0); \
  for (int64_t i = 0; i < a.n; i++) out = list_push_##Name(out, a.d[i]); \
  for (int64_t i = 0; i < b.n; i++) out = list_push_##Name(out, b.d[i]); \
  return out; \
}

TERSE_DECL_LIST(i64, int64_t)
TERSE_DECL_LIST(i32, int32_t)
TERSE_DECL_LIST(i16, int16_t)
TERSE_DECL_LIST(i8, int8_t)
TERSE_DECL_LIST(u64, uint64_t)
TERSE_DECL_LIST(u32, uint32_t)
TERSE_DECL_LIST(u16, uint16_t)
TERSE_DECL_LIST(f64, double)
TERSE_DECL_LIST(bool, bool)
/* char is i8 surface */
typedef List_i8 List_char;
static List_char list_new_char(int64_t n) { return list_new_i8(n); }
static List_char list_push_char(List_char L, int8_t v) { return list_push_i8(L, v); }
static int64_t list_len_char(List_char L) { return list_len_i8(L); }
static int8_t list_get_char(List_char L, int64_t i) { return list_get_i8(L, i); }
static List_char list_concat_char(List_char a, List_char b) { return list_concat_i8(a, b); }




static List_str map_str_i64_keys(Map_str_i64 m) {
  List_str out = list_new_str(0);
  for (int64_t i = 0; i < m.n; i++) out = list_push_str(out, m.k[i] ? m.k[i] : "");
  return out;
}
static List_str map_str_str_keys(Map_str_str m) {
  List_str out = list_new_str(0);
  for (int64_t i = 0; i < m.n; i++) out = list_push_str(out, m.k[i] ? m.k[i] : "");
  return out;
}
static List map_str_i64_values(Map_str_i64 m) {
  List out = list_new(0);
  for (int64_t i = 0; i < m.n; i++) out = list_push(out, m.v[i]);
  return out;
}

/* --- std.str surface (terse names) --- */
static int64_t str_has(const char* s, const char* sub) {
  if (!s) s = ""; if (!sub) sub = "";
  return strstr(s, sub) != NULL ? INT64_C(1) : INT64_C(0);
}
static int64_t str_starts(const char* s, const char* prefix) {
  if (!s) s = ""; if (!prefix) prefix = "";
  size_t n = strlen(prefix);
  return strncmp(s, prefix, n) == 0 ? INT64_C(1) : INT64_C(0);
}
static int64_t str_ends(const char* s, const char* suffix) {
  if (!s) s = ""; if (!suffix) suffix = "";
  size_t ns = strlen(s), n = strlen(suffix);
  if (n > ns) return INT64_C(0);
  return strcmp(s + (ns - n), suffix) == 0 ? INT64_C(1) : INT64_C(0);
}

static char* str_up(const char* s) {
  if (!s) s = "";
  size_t n = strlen(s);
  char* r = (char*)malloc(n + 1);
  for (size_t i = 0; i < n; i++) {
    unsigned char c = (unsigned char)s[i];
    r[i] = (c >= 'a' && c <= 'z') ? (char)(c - 32) : (char)c;
  }
  r[n] = 0;
  return r;
}
static char* str_low(const char* s) {
  if (!s) s = "";
  size_t n = strlen(s);
  char* r = (char*)malloc(n + 1);
  for (size_t i = 0; i < n; i++) {
    unsigned char c = (unsigned char)s[i];
    r[i] = (c >= 'A' && c <= 'Z') ? (char)(c + 32) : (char)c;
  }
  r[n] = 0;
  return r;
}
static char* str_trim(const char* s) {
  if (!s) s = "";
  while (*s == ' ' || *s == '\t' || *s == '\n' || *s == '\r') s++;
  size_t n = strlen(s);
  while (n > 0 && (s[n-1] == ' ' || s[n-1] == '\t' || s[n-1] == '\n' || s[n-1] == '\r')) n--;
  char* r = (char*)malloc(n + 1);
  memcpy(r, s, n); r[n] = 0;
  return r;
}
static int64_t str_parse_i64(const char* s) {
  if (!s) return INT64_C(0);
  while (*s == ' ' || *s == '\t') s++;
  int neg = 0;
  if (*s == '-') { neg = 1; s++; }
  else if (*s == '+') s++;
  int64_t v = 0; int any = 0;
  while (*s >= '0' && *s <= '9') {
    any = 1;
    v = v * 10 + (*s - '0');
    s++;
  }
  if (!any) return INT64_C(0);
  return neg ? -v : v;
}
static List_str str_split(const char* s, const char* sep) {
  List_str out = list_new_str(0);
  if (!s) s = "";
  if (!sep || !sep[0]) {
    /* empty sep → each character as its own string */
    for (const char* p = s; *p; p++) {
      char* one = (char*)malloc(2); one[0] = *p; one[1] = 0;
      out = list_push_str(out, one);
    }
    return out;
  }
  size_t sepn = strlen(sep);
  const char* start = s;
  for (;;) {
    const char* found = strstr(start, sep);
    size_t len = found ? (size_t)(found - start) : strlen(start);
    char* part = (char*)malloc(len + 1);
    if (!part) { fprintf(stderr, "oom split\n"); exit(1); }
    memcpy(part, start, len); part[len] = 0;
    out = list_push_str(out, part);
    if (!found) break;
    start = found + sepn;
  }
  return out;
}
static char* str_join(List_str parts, const char* sep) {
  if (!sep) sep = "";
  size_t sepn = strlen(sep);
  size_t total = 1;
  for (int64_t i = 0; i < parts.n; i++) {
    const char* pi = (parts.d && parts.d[i]) ? parts.d[i] : "";
    total += strlen(pi);
    if (i + 1 < parts.n) total += sepn;
  }
  char* r = (char*)malloc(total);
  if (!r) { fprintf(stderr, "oom join\n"); exit(1); }
  size_t off = 0;
  for (int64_t i = 0; i < parts.n; i++) {
    if (i && sepn) { memcpy(r + off, sep, sepn); off += sepn; }
    const char* pi = (parts.d && parts.d[i]) ? parts.d[i] : "";
    size_t li = strlen(pi);
    memcpy(r + off, pi, li); off += li;
  }
  r[off] = 0;
  return r;
}


static int _terse_did_print = 0;
static void print_int(int64_t x) { _terse_did_print = 1; printf("%lld\n", (long long)x); }
static void print_list(List L) {
  _terse_did_print = 1;
  printf("[");
  for (int64_t i = 0; i < L.n; i++) {
    if (i) printf(", ");
    printf("%lld", (long long)L.d[i]);
  }
  printf("]\n");
}
static void print_list_i64(List_i64 L) {
  _terse_did_print = 1;
  printf("[");
  for (int64_t i = 0; i < L.n; i++) {
    if (i) printf(", ");
    printf("%lld", (long long)L.d[i]);
  }
  printf("]\n");
}
static void print_list_i32(List_i32 L) {
  _terse_did_print = 1;
  printf("[");
  for (int64_t i = 0; i < L.n; i++) {
    if (i) printf(", ");
    printf("%d", (int)L.d[i]);
  }
  printf("]\n");
}
static void print_list_str(List_str L) {
  _terse_did_print = 1;
  printf("[");
  for (int64_t i = 0; i < L.n; i++) {
    if (i) printf(", ");
    printf("\"%s\"", L.d[i] ? L.d[i] : "");
  }
  printf("]\n");
}


static void print_i64(int64_t x) { _terse_did_print = 1; printf("%lld\n", (long long)x); }
static void print_bool(bool v) { _terse_did_print = 1; printf(v ? "true\n" : "false\n"); }
static void print_str(const char* s) { _terse_did_print = 1; printf("%s\n", s); }

/* -- std.tst assertion helpers (continue on failure; count via _tst_failures) -- */
static int64_t _tst_failures = 0;
static int64_t _tst_checks = 0;
static int64_t tst_eq_i64(int64_t got, int64_t expected, const char* file, int64_t line) {
  _tst_checks++;
  if (got != expected) {
    _tst_failures++;
    fprintf(stderr, "FAIL %s:%lld: expected %lld, got %lld\n",
            file ? file : "?", (long long)line, (long long)expected, (long long)got);
    return INT64_C(1);
  }
  return INT64_C(0);
}
static int64_t tst_eq_bool(bool got, bool expected, const char* file, int64_t line) {
  _tst_checks++;
  if (got != expected) {
    _tst_failures++;
    fprintf(stderr, "FAIL %s:%lld: expected %s, got %s\n",
            file ? file : "?", (long long)line,
            expected ? "true" : "false", got ? "true" : "false");
    return INT64_C(1);
  }
  return INT64_C(0);
}
static int64_t tst_eq_str(const char* got, const char* expected, const char* file, int64_t line) {
  _tst_checks++;
  const char* g = got ? got : "";
  const char* e = expected ? expected : "";
  if (strcmp(g, e) != 0) {
    _tst_failures++;
    fprintf(stderr, "FAIL %s:%lld: expected \"%s\", got \"%s\"\n",
            file ? file : "?", (long long)line, e, g);
    return INT64_C(1);
  }
  return INT64_C(0);
}
static int64_t tst_ne_i64(int64_t got, int64_t unexpected, const char* file, int64_t line) {
  _tst_checks++;
  if (got == unexpected) {
    _tst_failures++;
    fprintf(stderr, "FAIL %s:%lld: expected not %lld, got %lld\n",
            file ? file : "?", (long long)line, (long long)unexpected, (long long)got);
    return INT64_C(1);
  }
  return INT64_C(0);
}
static int64_t tst_ne_bool(bool got, bool unexpected, const char* file, int64_t line) {
  _tst_checks++;
  if (got == unexpected) {
    _tst_failures++;
    fprintf(stderr, "FAIL %s:%lld: expected not %s, got %s\n",
            file ? file : "?", (long long)line,
            unexpected ? "true" : "false", got ? "true" : "false");
    return INT64_C(1);
  }
  return INT64_C(0);
}
static int64_t tst_ne_str(const char* got, const char* unexpected, const char* file, int64_t line) {
  _tst_checks++;
  const char* g = got ? got : "";
  const char* u = unexpected ? unexpected : "";
  if (strcmp(g, u) == 0) {
    _tst_failures++;
    fprintf(stderr, "FAIL %s:%lld: expected not \"%s\", got \"%s\"\n",
            file ? file : "?", (long long)line, u, g);
    return INT64_C(1);
  }
  return INT64_C(0);
}
static int64_t tst_report(void) {
  /* Quiet on success: only print failures (and SKIP when implemented). */
  _terse_did_print = 1; /* suppress main's leftover numeric print */
  if (_tst_failures != 0) {
    fprintf(stderr, "FAILED %lld of %lld check(s)\n",
            (long long)_tst_failures, (long long)_tst_checks);
  }
  return _tst_failures;
}

static char* json_int(int64_t x) {
  char* b = (char*)malloc(32);
  snprintf(b, 32, "%lld", (long long)x);
  return b;
}
static char* json_str(const char* s) {
  size_t n = strlen(s);
  char* b = (char*)malloc(n + 3);
  b[0] = '"'; memcpy(b+1, s, n); b[n+1] = '"'; b[n+2] = 0;
  return b;
}
static char* json_list(List L) {
  /* rough buffer */
  size_t cap = 64 + L.n * 24;
  char* b = (char*)malloc(cap);
  size_t o = 0;
  b[o++] = '[';
  for (int64_t i = 0; i < L.n; i++) {
    if (i) b[o++] = ',';
    o += (size_t)snprintf(b+o, cap-o, "%lld", (long long)L.d[i]);
  }
  b[o++] = ']'; b[o] = 0;
  return b;
}
static void json_field_prefix(char* b, size_t* o, size_t cap, int* first, const char* name) {
    *o += (size_t)snprintf(b + *o, cap - *o, "%s\"%s\":", *first ? "" : ",", name);
    *first = 0;
}
static void json_append_i64(char* b, size_t* o, size_t cap, int* first, const char* name, int64_t value) {
    json_field_prefix(b, o, cap, first, name);
    *o += (size_t)snprintf(b + *o, cap - *o, "%lld", (long long)value);
}
static void json_append_bool(char* b, size_t* o, size_t cap, int* first, const char* name, bool value) {
    json_field_prefix(b, o, cap, first, name);
    *o += (size_t)snprintf(b + *o, cap - *o, "%s", value ? "true" : "false");
}
static void json_append_f64(char* b, size_t* o, size_t cap, int* first, const char* name, double value) {
    json_field_prefix(b, o, cap, first, name);
    *o += (size_t)snprintf(b + *o, cap - *o, "%g", value);
}
static void json_append_str(char* b, size_t* o, size_t cap, int* first, const char* name, const char* value) {
    json_field_prefix(b, o, cap, first, name);
    *o += (size_t)snprintf(b + *o, cap - *o, "\"%s\"", value ? value : "");
}

static const char* env_get(const char* k) {
  const char* v = getenv(k);
  return v ? v : "";
}
#ifndef _WIN32
int setenv(const char *name, const char *value, int overwrite);
#endif
static int64_t env_set(const char* k, const char* v) {
  if (!k) return INT64_C(-1);
#ifdef _WIN32
  /* _putenv_s is preferred on Windows */
  return (_putenv_s(k, v ? v : "") == 0) ? INT64_C(0) : INT64_C(-1);
#else
  return (setenv(k, v ? v : "", 1) == 0) ? INT64_C(0) : INT64_C(-1);
#endif
}

static int terse_argc = 0;
static char** terse_argv = NULL;

static const char* terse_arg(int64_t index) {
    if (index < 0 || index >= terse_argc) return "";
    return terse_argv[index];
}

static int64_t terse_gcc_compile(const char* source, const char* output) {
    /* -O0: large statement-expr C can crash Apple clang at -O2 */
    char* args[24];
    int count = 0;
    const char* cc = getenv("CC");
    if (!cc || !cc[0]) cc = "gcc";
    args[count++] = (char*)cc;
    args[count++] = "-O0";
    args[count++] = "-std=c11";
    args[count++] = "-Wno-unused-function";
    args[count++] = "-Wno-unused-parameter";
    args[count++] = "-Wno-unused-value";
    args[count++] = "-Wno-parentheses";
    args[count++] = (char*)source;
#ifdef _WIN32
    args[count++] = "-lws2_32";
#endif
    args[count++] = "-o";
    args[count++] = (char*)output;
    args[count] = NULL;
#ifdef _WIN32
    return (int64_t)_spawnvp(_P_WAIT, cc, (const char* const*)args);
#else
    pid_t child = fork();
    if (child < 0) {
        perror("tc: fork");
        return 1;
    }
    if (child == 0) {
        execvp(cc, args);
        perror("tc: exec CC");
        _exit(127);
    }
    int status = 0;
    if (waitpid(child, &status, 0) < 0) {
        perror("tc: wait for CC");
        return 1;
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 1;
#endif
}

static void fs_io_fail(const char* operation, const char* path) {
    fprintf(stderr, "file %s failed for '%s': %s\n", operation, path, strerror(errno));
    exit(1);
}

static char* fs_read_text(const char* path) {
    FILE* file = fopen(path, "rb");
    if (!file) fs_io_fail("read", path);
    if (fseek(file, 0, SEEK_END) != 0) fs_io_fail("read", path);
    long size = ftell(file);
    if (size < 0 || fseek(file, 0, SEEK_SET) != 0) fs_io_fail("read", path);
    char* text = (char*)malloc((size_t)size + 1);
    if (!text) { fclose(file); fprintf(stderr, "out of memory reading '%s'\n", path); exit(1); }
    size_t read_size = fread(text, 1, (size_t)size, file);
    if (ferror(file)) fs_io_fail("read", path);
    if (fclose(file) != 0) fs_io_fail("read", path);
    text[read_size] = 0;
    return text;
}

static int64_t fs_write_text(const char* path, const char* text) {
    FILE* file = fopen(path, "wb");
    if (!file) fs_io_fail("write", path);
    size_t size = strlen(text);
    size_t written = fwrite(text, 1, size, file);
    if (written != size || fclose(file) != 0) fs_io_fail("write", path);
    return (int64_t)written;
}

static int64_t fs_append_text(const char* path, const char* text) {
    FILE* file = fopen(path, "ab");
    if (!file) fs_io_fail("append", path);
    size_t size = text ? strlen(text) : 0;
    size_t written = size ? fwrite(text, 1, size, file) : 0;
    if (written != size || fclose(file) != 0) fs_io_fail("append", path);
    return (int64_t)written;
}

/* -- minimal HTTP/1.1 server -- */
typedef const char* (*route_fn)(const char* method, const char* path, const char* body);

static void http_send(sock_t fd, int code, const char* ctype, const char* body) {
  char hdr[512];
  int blen = body ? (int)strlen(body) : 0;
  const char* msg =
    code==200 ? "OK" : code==201 ? "Created" : code==204 ? "No Content" :
    code==400 ? "Bad Request" : code==401 ? "Unauthorized" : code==403 ? "Forbidden" :
    code==404 ? "Not Found" : code==405 ? "Method Not Allowed" : code==409 ? "Conflict" :
    code==500 ? "Internal Server Error" : "Error";
  int n = snprintf(hdr, sizeof(hdr),
    "HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\n\r\n",
    code, msg, ctype, blen);
  send(fd, hdr, n, 0);
  if (body && blen) send(fd, body, blen, 0);
}

/* Handler returning status + body + content-type (for http.serve(port, fn)) */
typedef struct { int64_t status; const char* body; const char* ctype; } HttpResC;
typedef HttpResC (*http_res_fn)(const char* method, const char* path, const char* query, const char* body);

static void http_serve_fn(int64_t port, http_res_fn handler) {
  sock_init();
#ifndef _WIN32
  signal(SIGPIPE, SIG_IGN);
#endif
  sock_t srv = socket(AF_INET, SOCK_STREAM, 0);
  if (srv == (sock_t)SOCK_ERR) { fprintf(stderr, "socket failed\n"); exit(1); }
  int yes = 1;
  setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, (const char*)&yes, sizeof(yes));
  struct sockaddr_in addr;
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons((uint16_t)port);
  if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) == SOCK_ERR) {
    fprintf(stderr, "bind failed\n"); exit(1);
  }
  if (listen(srv, 64) == SOCK_ERR) { fprintf(stderr, "listen failed\n"); exit(1); }
  fprintf(stderr, "terse http listening on :%lld\n", (long long)port);
  for (;;) {
    sock_t cli = accept(srv, NULL, NULL);
    if (cli == (sock_t)SOCK_ERR) continue;
    char buf[65536];
    int n = (int)recv(cli, buf, sizeof(buf)-1, 0);
    if (n <= 0) { CLOSESOCK(cli); continue; }
    buf[n] = 0;
    char method[16] = {0}, path[2048] = {0};
    sscanf(buf, "%15s %2047s", method, path);
    char* q = strchr(path, '?');
    char query[2048] = {0};
    if (q) { strncpy(query, q + 1, sizeof(query)-1); *q = 0; }
    char* sep = strstr(buf, "\r\n\r\n");
    int content_length = 0;
    char* content_header = strstr(buf, "Content-Length:");
    if (content_header) sscanf(content_header, "Content-Length: %d", &content_length);
    int header_length = sep ? (int)(sep - buf) + 4 : n;
    while (sep && n < header_length + content_length && n < (int)sizeof(buf) - 1) {
      int received = (int)recv(cli, buf + n, sizeof(buf) - 1 - n, 0);
      if (received <= 0) break;
      n += received;
      buf[n] = 0;
    }
    const char* body = "";
    if (sep) body = sep + 4;
    HttpResC resp = handler(method, path, query, body);
    int code = (int)resp.status;
    const char* ctype = resp.ctype ? resp.ctype : "text/plain";
    const char* rbody = resp.body ? resp.body : "";
    http_send(cli, code, ctype, rbody);
    CLOSESOCK(cli);
  }
}

static void http_serve_run(int64_t port, route_fn handler) {
  sock_init();
#ifndef _WIN32
  signal(SIGPIPE, SIG_IGN);
#endif
  sock_t srv = socket(AF_INET, SOCK_STREAM, 0);
  if (srv == (sock_t)SOCK_ERR) { fprintf(stderr, "socket failed\n"); exit(1); }
  int yes = 1;
  setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, (const char*)&yes, sizeof(yes));
  struct sockaddr_in addr;
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  addr.sin_port = htons((uint16_t)port);
  if (bind(srv, (struct sockaddr*)&addr, sizeof(addr)) == SOCK_ERR) {
    fprintf(stderr, "bind failed\n"); exit(1);
  }
  if (listen(srv, 64) == SOCK_ERR) { fprintf(stderr, "listen failed\n"); exit(1); }
  fprintf(stderr, "terse http listening on :%lld\n", (long long)port);
  for (;;) {
    sock_t cli = accept(srv, NULL, NULL);
    if (cli == (sock_t)SOCK_ERR) continue;
    char buf[65536];
    int n = (int)recv(cli, buf, sizeof(buf)-1, 0);
    if (n <= 0) { CLOSESOCK(cli); continue; }
    buf[n] = 0;
    char method[16] = {0}, path[2048] = {0};
    sscanf(buf, "%15s %2047s", method, path);
    char* sep = strstr(buf, "\r\n\r\n");
        int content_length = 0;
        char* content_header = strstr(buf, "Content-Length:");
        if (content_header) sscanf(content_header, "Content-Length: %d", &content_length);
        int header_length = sep ? (int)(sep - buf) + 4 : n;
        while (sep && n < header_length + content_length && n < (int)sizeof(buf) - 1) {
            int received = (int)recv(cli, buf + n, sizeof(buf) - 1 - n, 0);
            if (received <= 0) break;
            n += received;
            buf[n] = 0;
        }
        const char* body = "";
    if (sep) body = sep + 4;
    const char* resp = handler(method, path, body);
    if (resp)
      http_send(cli, 200, "application/json; charset=utf-8", resp);
    else
      http_send(cli, 404, "text/plain", "not found");
    CLOSESOCK(cli);
  }
}
