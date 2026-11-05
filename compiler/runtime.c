
#if !defined(_WIN32)
#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200112L
#endif
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#ifdef _WIN32
#include <process.h>
#else
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#endif


/* --- Arena (bump) memory management --------------------------------------
 * All Terse runtime heap traffic (lists, maps, strings) goes through the
 * arena. Chunks are allocated with system malloc; individual objects are
 * bump-allocated and never freed individually. Suitable for batch / server
 * request scopes and whole-program globals.
 * ----------------------------------------------------------------------- */
typedef struct ArenaChunk {
  struct ArenaChunk *next;
  size_t size;
  size_t used;
  /* flexible array: char data[]; — use offset after struct */
} ArenaChunk;

static ArenaChunk *_arena_head = NULL;
static size_t _arena_chunk_cap = 256u * 1024u;
static size_t _arena_bytes = 0;   /* bytes handed to clients */
static size_t _arena_chunks = 0;

static void *arena_sys_malloc(size_t n) {
  void *p = malloc(n);
  if (!p) { fprintf(stderr, "arena: system OOM (%zu bytes)\n", n); exit(1); }
  return p;
}

static void *arena_alloc(size_t n) {
  if (n == 0) n = 1;
  /* header (size_t) + payload, 8-byte aligned */
  size_t need = sizeof(size_t) + n;
  need = (need + 7u) & ~(size_t)7u;
  if (!_arena_head || _arena_head->used + need > _arena_head->size) {
    size_t cap = need > _arena_chunk_cap ? need : _arena_chunk_cap;
    ArenaChunk *c = (ArenaChunk *)arena_sys_malloc(sizeof(ArenaChunk) + cap);
    c->next = _arena_head;
    c->size = cap;
    c->used = 0;
    _arena_head = c;
    _arena_chunks++;
  }
  char *base = (char *)(_arena_head + 1) + _arena_head->used;
  _arena_head->used += need;
  _arena_bytes += n;
  size_t *hdr = (size_t *)base;
  *hdr = n;
  return (void *)(hdr + 1);
}

static void *arena_calloc(size_t count, size_t size) {
  size_t total = count * size;
  void *p = arena_alloc(total);
  memset(p, 0, total);
  return p;
}

/* Bump realloc: allocate fresh block and copy; old block is abandoned. */
static void *arena_realloc(void *ptr, size_t new_n) {
  size_t old_n = 0;
  if (ptr) old_n = ((size_t *)ptr)[-1];
  void *p = arena_alloc(new_n);
  if (ptr && old_n) {
    size_t copy = old_n < new_n ? old_n : new_n;
    memcpy(p, ptr, copy);
  }
  return p;
}

static char *arena_strdup(const char *s) {
  if (!s) s = "";
  size_t n = strlen(s);
  char *d = (char *)arena_alloc(n + 1);
  memcpy(d, s, n + 1);
  return d;
}

/* Bytes currently live in the arena (approximate client payload). */
static int64_t arena_used(void) { return (int64_t)_arena_bytes; }
static int64_t arena_chunk_count(void) { return (int64_t)_arena_chunks; }

/* Optional: release all arena chunks (tests / request end). */
static void arena_reset(void) {
  while (_arena_head) {
    ArenaChunk *n = _arena_head->next;
    free(_arena_head);
    _arena_head = n;
  }
  _arena_bytes = 0;
  _arena_chunks = 0;
}

typedef struct TerseTrap {
  jmp_buf env;
  struct TerseTrap *prev;
} TerseTrap;

static TerseTrap *_terse_trap = NULL;
static const char *_terse_error_message = NULL;

static void terse_err(const char *message) {
  if (!message) message = "";
  if (_terse_trap) {
    _terse_error_message = message;
    longjmp(_terse_trap->env, 1);
  }
  fprintf(stderr, "uncaught error: %s\n", message);
  exit(1);
}


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
#include <netdb.h>
#include <openssl/ssl.h>
#include <openssl/err.h>
  #include <arpa/inet.h>
  #include <signal.h>
  typedef int sock_t;
  #define CLOSESOCK close
  #define SOCK_ERR (-1)
  static void sock_init(void) {}
  static void sock_fini(void) {}
#endif

/* --- basic TCP sockets (host surface; HTTP lives in lib/http.te) --- */

#ifndef TERSE_NO_TLS
#define TERSE_TLS_MAX 64
typedef struct {
  int active;
  sock_t fd;
  SSL *ssl;
  SSL_CTX *ctx;
} TerseTlsSlot;
static TerseTlsSlot terse_tls_slots[TERSE_TLS_MAX];
static int terse_tls_inited = 0;
static int terse_tls_find(sock_t fd);
static void terse_tls_free_slot(int i);
#endif


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
  if (n <= 0) { char* e = (char*)arena_alloc(1); e[0]=0; return e; }
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
  char* out = (char*)arena_alloc((size_t)n + 1);
  memcpy(out, buf, (size_t)n);
  out[n] = 0;
  return out;
}
static int64_t sock_send(int64_t fd, const char* data) {
  sock_t s = (sock_t)(intptr_t)fd;
  if (!data) data = "";
  int n = (int)strlen(data);
  int sent = 0;
#ifndef TERSE_NO_TLS
  int ti = terse_tls_find(s);
  if (ti >= 0) {
    SSL *ssl = terse_tls_slots[ti].ssl;
    while (sent < n) {
      int k = SSL_write(ssl, data + sent, n - sent);
      if (k <= 0) break;
      sent += k;
    }
    return (int64_t)sent;
  }
#endif
  while (sent < n) {
    int k = (int)send(s, data + sent, (size_t)(n - sent), 0);
    if (k <= 0) break;
    sent += k;
  }
  return (int64_t)sent;
}
static int64_t sock_close(int64_t fd) {
  sock_t s = (sock_t)(intptr_t)fd;
#ifndef TERSE_NO_TLS
  int ti = terse_tls_find(s);
  if (ti >= 0) terse_tls_free_slot(ti);
#endif
#ifdef _WIN32
  shutdown(s, SD_BOTH);
#else
  shutdown(s, SHUT_RDWR);
#endif
  CLOSESOCK(s);
  return INT64_C(0);
}

/* TCP client connect. host: hostname or dotted IP. returns fd or -1. */
static int64_t sock_connect(const char* host, int64_t port) {
  sock_init();
#ifndef _WIN32
  signal(SIGPIPE, SIG_IGN);
#endif
  if (!host || !*host) return INT64_C(-1);
  char portbuf[16];
  snprintf(portbuf, sizeof(portbuf), "%lld", (long long)port);
  struct addrinfo hints, *res = NULL, *rp;
  memset(&hints, 0, sizeof(hints));
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;
  int gai = getaddrinfo(host, portbuf, &hints, &res);
  if (gai != 0 || !res) return INT64_C(-1);
  sock_t fd = (sock_t)SOCK_ERR;
  for (rp = res; rp; rp = rp->ai_next) {
    fd = socket(rp->ai_family, rp->ai_socktype, rp->ai_protocol);
    if (fd == (sock_t)SOCK_ERR) continue;
    if (connect(fd, rp->ai_addr, (int)rp->ai_addrlen) == 0) break;
    CLOSESOCK(fd);
    fd = (sock_t)SOCK_ERR;
  }
  freeaddrinfo(res);
  if (fd == (sock_t)SOCK_ERR) return INT64_C(-1);
  return (int64_t)(intptr_t)fd;
}

/* Read until connection close or buffer full (for HTTP client responses). */

/* --- TLS (OpenSSL) client sessions keyed by socket fd --- */
#ifndef TERSE_NO_TLS
static void terse_tls_init(void) {
  if (terse_tls_inited) return;
  SSL_library_init();
  SSL_load_error_strings();
  OpenSSL_add_all_algorithms();
  terse_tls_inited = 1;
}

static int terse_tls_find(sock_t fd) {
  for (int i = 0; i < TERSE_TLS_MAX; i++)
    if (terse_tls_slots[i].active && terse_tls_slots[i].fd == fd) return i;
  return -1;
}

static int terse_tls_alloc(sock_t fd, SSL *ssl, SSL_CTX *ctx) {
  for (int i = 0; i < TERSE_TLS_MAX; i++) {
    if (!terse_tls_slots[i].active) {
      terse_tls_slots[i].active = 1;
      terse_tls_slots[i].fd = fd;
      terse_tls_slots[i].ssl = ssl;
      terse_tls_slots[i].ctx = ctx;
      return i;
    }
  }
  return -1;
}

static void terse_tls_free_slot(int i) {
  if (i < 0 || i >= TERSE_TLS_MAX || !terse_tls_slots[i].active) return;
  if (terse_tls_slots[i].ssl) {
    SSL_shutdown(terse_tls_slots[i].ssl);
    SSL_free(terse_tls_slots[i].ssl);
  }
  if (terse_tls_slots[i].ctx) SSL_CTX_free(terse_tls_slots[i].ctx);
  terse_tls_slots[i].active = 0;
  terse_tls_slots[i].ssl = NULL;
  terse_tls_slots[i].ctx = NULL;
}

/* TCP + TLS handshake. Returns fd or -1. */
static int64_t sock_connect_tls(const char* host, int64_t port) {
  if (!host || !*host) return INT64_C(-1);
  int64_t raw = sock_connect(host, port);
  if (raw < 0) return raw;
  sock_t fd = (sock_t)(intptr_t)raw;
  terse_tls_init();
  SSL_CTX *ctx = SSL_CTX_new(TLS_client_method());
  if (!ctx) { CLOSESOCK(fd); return INT64_C(-1); }
  SSL_CTX_set_default_verify_paths(ctx);
  SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER, NULL);
  SSL *ssl = SSL_new(ctx);
  if (!ssl) { SSL_CTX_free(ctx); CLOSESOCK(fd); return INT64_C(-1); }
  SSL_set_fd(ssl, (int)fd);
  SSL_set_tlsext_host_name(ssl, host);
  /* OpenSSL 1.1+ hostname check */
#if OPENSSL_VERSION_NUMBER >= 0x10100000L
  SSL_set1_host(ssl, host);
#endif
  if (SSL_connect(ssl) != 1) {
    fprintf(stderr, "sock.connect_tls: handshake failed for %s\n", host);
    ERR_print_errors_fp(stderr);
    SSL_free(ssl);
    SSL_CTX_free(ctx);
    CLOSESOCK(fd);
    return INT64_C(-1);
  }
  if (terse_tls_alloc(fd, ssl, ctx) < 0) {
    SSL_shutdown(ssl); SSL_free(ssl); SSL_CTX_free(ctx); CLOSESOCK(fd);
    return INT64_C(-1);
  }
  return raw;
}
#else
static int64_t sock_connect_tls(const char* host, int64_t port) {
  (void)host; (void)port;
  fprintf(stderr, "sock.connect_tls: TLS not built (define without TERSE_NO_TLS and link -lssl -lcrypto)\n");
  return INT64_C(-1);
}
#endif

static char* sock_recv_all(int64_t fd) {
  sock_t s = (sock_t)(intptr_t)fd;
#ifdef _WIN32
  DWORD tv = 10000;
  setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));
#else
  struct timeval tv; tv.tv_sec = 10; tv.tv_usec = 0;
  setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char*)&tv, sizeof(tv));
#endif
  size_t cap = 8192, n = 0;
  char* buf = (char*)malloc(cap);
  if (!buf) { char* e = (char*)arena_alloc(1); e[0]=0; return e; }
#ifndef TERSE_NO_TLS
  int ti = terse_tls_find(s);
  SSL *ssl = (ti >= 0) ? terse_tls_slots[ti].ssl : NULL;
#else
  void *ssl = NULL;
#endif
  for (;;) {
    if (n + 2048 >= cap) {
      cap *= 2;
      char* nb = (char*)realloc(buf, cap);
      if (!nb) break;
      buf = nb;
    }
    int got;
#ifndef TERSE_NO_TLS
    if (ssl) {
      got = SSL_read(ssl, buf + n, (int)(cap - n - 1));
    } else
#endif
    {
      got = (int)recv(s, buf + n, (int)(cap - n - 1), 0);
    }
    if (got <= 0) break;
    n += (size_t)got;
    buf[n] = 0;
    /* stop early if headers+body complete */
    char* sep = strstr(buf, "\r\n\r\n");
    if (sep) {
      int content_length = -1;
      char* cl = strstr(buf, "Content-Length:");
      if (!cl) cl = strstr(buf, "content-length:");
      if (cl) sscanf(cl, "%*[^:]: %d", &content_length);
      int header_len = (int)(sep - buf) + 4;
      if (content_length >= 0 && (int)n >= header_len + content_length) break;
      /* no content-length: keep reading until peer closes or timeout */
    }
  }
  buf[n] = 0;
  char* out = (char*)arena_alloc(n + 1);
  if (out) { memcpy(out, buf, n + 1); }
  free(buf);
  if (!out) { char* e = (char*)arena_alloc(1); e[0]=0; return e; }
  return out;
}



/* --- non-blocking multi-connection HTTP (select) --- */
#ifndef SOCK_NB_AGAIN
#define SOCK_NB_AGAIN (-2)
#endif

static void sock_set_nonblock(sock_t s) {
#ifdef _WIN32
  u_long mode = 1;
  ioctlsocket(s, FIONBIO, &mode);
#else
  int fl = fcntl(s, F_GETFL, 0);
  if (fl >= 0) fcntl(s, F_SETFL, fl | O_NONBLOCK);
#endif
}

static int64_t sock_listen_nb(int64_t port) {
  int64_t fd = sock_listen(port);
  sock_set_nonblock((sock_t)(intptr_t)fd);
  return fd;
}

static int64_t sock_accept_nb(int64_t listen_fd) {
  sock_t srv = (sock_t)(intptr_t)listen_fd;
  sock_t cli = accept(srv, NULL, NULL);
  if (cli == (sock_t)SOCK_ERR) {
#ifdef _WIN32
    int e = WSAGetLastError();
    if (e == WSAEWOULDBLOCK) return SOCK_NB_AGAIN;
#else
    if (errno == EAGAIN || errno == EWOULDBLOCK) return SOCK_NB_AGAIN;
#endif
    return INT64_C(-1);
  }
  sock_set_nonblock(cli);
  return (int64_t)(intptr_t)cli;
}

typedef char* (*sock_nb_handler_fn)(const char* raw);

typedef struct {
  sock_t fd;
  char* in;
  int in_cap;
  int in_n;
  char* out;
  int out_off;
  int out_len;
  int st; /* 0=read 1=write */
  int active;
} SockNbConn;

#define SOCK_NB_MAX 64
#define SOCK_NB_IN_CAP 16384

static int sock_nb_request_complete(const char* buf, int n) {
  char* sep = strstr(buf, "\r\n\r\n");
  if (!sep) return 0;
  int header_len = (int)(sep - buf) + 4;
  int content_length = 0;
  const char* cl = strstr(buf, "Content-Length:");
  if (cl) sscanf(cl, "Content-Length: %d", &content_length);
  return n >= header_len + content_length;
}

/* Concurrent non-blocking HTTP server. handler(raw_request) -> full response bytes. */
static void sock_nb_srv(int64_t port, sock_nb_handler_fn handler) {
  int64_t lfd = sock_listen_nb(port);
  sock_t listen_s = (sock_t)(intptr_t)lfd;
  SockNbConn* conns = (SockNbConn*)calloc(SOCK_NB_MAX, sizeof(SockNbConn));
  if (!conns) { fprintf(stderr, "sock.nb_srv: oom\n"); exit(1); }
  fprintf(stderr, "sock.nb_srv non-blocking on :%lld\n", (long long)port);
  for (;;) {
    fd_set rfds, wfds;
    FD_ZERO(&rfds); FD_ZERO(&wfds);
    FD_SET(listen_s, &rfds);
    sock_t maxfd = listen_s;
    for (int i = 0; i < SOCK_NB_MAX; i++) {
      if (!conns[i].active) continue;
      if (conns[i].st == 0) FD_SET(conns[i].fd, &rfds);
      else FD_SET(conns[i].fd, &wfds);
      if (conns[i].fd > maxfd) maxfd = conns[i].fd;
    }
    struct timeval tv; tv.tv_sec = 1; tv.tv_usec = 0;
    int rc = select((int)maxfd + 1, &rfds, &wfds, NULL, &tv);
    if (rc < 0) continue;
    if (FD_ISSET(listen_s, &rfds)) {
      for (;;) {
        int64_t c = sock_accept_nb(lfd);
        if (c == SOCK_NB_AGAIN || c < 0) break;
        int slot = -1;
        for (int i = 0; i < SOCK_NB_MAX; i++) if (!conns[i].active) { slot = i; break; }
        if (slot < 0) { CLOSESOCK((sock_t)(intptr_t)c); break; }
        conns[slot].fd = (sock_t)(intptr_t)c;
        conns[slot].in = (char*)malloc(SOCK_NB_IN_CAP);
        conns[slot].in_cap = SOCK_NB_IN_CAP;
        conns[slot].in_n = 0;
        if (conns[slot].in) conns[slot].in[0] = 0;
        conns[slot].out = NULL;
        conns[slot].out_off = 0;
        conns[slot].out_len = 0;
        conns[slot].st = 0;
        conns[slot].active = 1;
      }
    }
    for (int i = 0; i < SOCK_NB_MAX; i++) {
      if (!conns[i].active) continue;
      if (conns[i].st == 0 && FD_ISSET(conns[i].fd, &rfds)) {
        if (!conns[i].in) { CLOSESOCK(conns[i].fd); conns[i].active = 0; continue; }
        int space = conns[i].in_cap - 1 - conns[i].in_n;
        if (space <= 0) { free(conns[i].in); CLOSESOCK(conns[i].fd); conns[i].active = 0; continue; }
        int got = (int)recv(conns[i].fd, conns[i].in + conns[i].in_n, space, 0);
        if (got <= 0) {
#ifdef _WIN32
          int e = WSAGetLastError();
          if (e == WSAEWOULDBLOCK) continue;
#else
          if (errno == EAGAIN || errno == EWOULDBLOCK) continue;
#endif
          free(conns[i].in); conns[i].in = NULL; CLOSESOCK(conns[i].fd); conns[i].active = 0; continue;
        }
        conns[i].in_n += got;
        conns[i].in[conns[i].in_n] = 0;
        if (sock_nb_request_complete(conns[i].in, conns[i].in_n)) {
          char* resp = handler(conns[i].in);
          if (!resp) resp = (char*)"HTTP/1.1 500 Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
          conns[i].out = resp;
          conns[i].out_len = (int)strlen(resp);
          conns[i].out_off = 0;
          conns[i].st = 1;
        }
      } else if (conns[i].st == 1 && FD_ISSET(conns[i].fd, &wfds)) {
        int left = conns[i].out_len - conns[i].out_off;
        if (left <= 0) { CLOSESOCK(conns[i].fd); conns[i].active = 0; continue; }
        int k = (int)send(conns[i].fd, conns[i].out + conns[i].out_off, (size_t)left, 0);
        if (k <= 0) {
#ifdef _WIN32
          int e = WSAGetLastError();
          if (e == WSAEWOULDBLOCK) continue;
#else
          if (errno == EAGAIN || errno == EWOULDBLOCK) continue;
#endif
          CLOSESOCK(conns[i].fd); conns[i].active = 0; continue;
        }
        conns[i].out_off += k;
        if (conns[i].out_off >= conns[i].out_len) {
          free(conns[i].in); conns[i].in = NULL;
          CLOSESOCK(conns[i].fd);
          conns[i].active = 0;
        }
      }
    }
  }
}

typedef struct { int64_t *d; int64_t n; } List;

static List list_new(int64_t n) {
  List L; L.n = n; L.d = (int64_t*)arena_alloc(sizeof(int64_t) * (size_t)(n > 0 ? n : 1));
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
    L.d = (int64_t*)arena_realloc(L.d, sizeof(int64_t) * (size_t)(L.n + 1));
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
    m.k = (const char**)arena_realloc((void*)m.k, sizeof(const char*) * (size_t)m.cap);
    m.v = (int64_t*)arena_realloc(m.v, sizeof(int64_t) * (size_t)m.cap);
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
    m.k = (const char**)arena_realloc((void*)m.k, sizeof(const char*) * (size_t)m.cap);
    m.v = (const char**)arena_realloc((void*)m.v, sizeof(const char*) * (size_t)m.cap);
  }
  m.k[m.n] = key; m.v[m.n] = val; m.n++; return m;
}



typedef struct {
    int kind; /* 0 = integer, 1 = string */
    int64_t integer;
    const char* string;
} DbValue;


static char* str_from_i64(int64_t x) {
  char* b = (char*)arena_alloc(32);
  snprintf(b, 32, "%lld", (long long)x);
  return b;
}
static char* str_from_bool(bool v) {
  const char* s = v ? "true" : "false";
  size_t n = strlen(s);
  char* b = (char*)arena_alloc(n + 1);
  memcpy(b, s, n + 1);
  return b;
}
static char* str_concat(const char* a, const char* b) {
  size_t na = strlen(a), nb = strlen(b);
  char* r = (char*)arena_alloc(na + nb + 1);
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
    char* result = (char*)arena_alloc((size_t)length + 1);
    if (!result) { fprintf(stderr, "out of memory slicing string\n"); exit(1); }
    memcpy(result, s + start, (size_t)length);
    result[length] = 0;
    return result;
}

static char* str_slice_range(const char* s, int64_t start, int64_t end) {
  int64_t size = str_len(s);
  if (start < 0) start = 0;
  if (start > size) start = size;
  if (end < 0) end = 0;
  if (end > size) end = size;
  return str_slice(s, start, end > start ? end - start : 0);
}

/* --- [str] lists --- */
typedef struct { const char **d; int64_t n; int64_t cap; } List_str;
static List_str list_new_str(int64_t n) {
  List_str L = {NULL, 0, n};
  if (n > 0) { L.d = (const char**)arena_calloc((size_t)n, sizeof(const char*)); L.n = n; }
  return L;
}
static List_str list_push_str(List_str L, const char* v) {
  if (L.n >= L.cap) {
    L.cap = L.cap ? L.cap * 2 : 8;
    L.d = (const char**)arena_realloc((void*)L.d, sizeof(const char*) * (size_t)L.cap);
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
  if (n > 0) L.d = (CType*)arena_calloc((size_t)n, sizeof(CType)); \
  return L; \
} \
static List_##Name list_push_##Name(List_##Name L, CType v) { \
  if (L.n >= L.cap) { L.cap = L.cap ? L.cap * 2 : 8; L.d = (CType*)arena_realloc(L.d, (size_t)L.cap * sizeof(CType)); } \
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
TERSE_DECL_LIST(u8, uint8_t)
TERSE_DECL_LIST(u64, uint64_t)
TERSE_DECL_LIST(u32, uint32_t)
TERSE_DECL_LIST(u16, uint16_t)
TERSE_DECL_LIST(f32, float)
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

static char* str_trim(const char* s) {
  if (!s) s = "";
  while (*s == ' ' || *s == '\t' || *s == '\n' || *s == '\r') s++;
  size_t n = strlen(s);
  while (n > 0 && (s[n-1] == ' ' || s[n-1] == '\t' || s[n-1] == '\n' || s[n-1] == '\r')) n--;
  char* r = (char*)arena_alloc(n + 1);
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
static char* str_join(List_str parts, const char* sep) {
  if (!sep) sep = "";
  size_t sepn = strlen(sep);
  size_t total = 1;
  for (int64_t i = 0; i < parts.n; i++) {
    const char* pi = (parts.d && parts.d[i]) ? parts.d[i] : "";
    total += strlen(pi);
    if (i + 1 < parts.n) total += sepn;
  }
  char* r = (char*)arena_alloc(total);
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
  char* b = (char*)arena_alloc(32);
  snprintf(b, 32, "%lld", (long long)x);
  return b;
}
static char* json_str(const char* s) {
  size_t n = strlen(s);
  char* b = (char*)arena_alloc(n + 3);
  b[0] = '"'; memcpy(b+1, s, n); b[n+1] = '"'; b[n+2] = 0;
  return b;
}
static char* json_list(List L) {
  /* rough buffer */
  size_t cap = 64 + L.n * 24;
  char* b = (char*)arena_alloc(cap);
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
    char* text = (char*)arena_alloc((size_t)size + 1);
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
