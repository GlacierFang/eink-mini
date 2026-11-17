#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>

// 极简 JSON 解析器：够用即可，不追求完备。
// 固定容量，不做堆分配，避免长期运行 fragmentation。
enum JType : uint8_t { J_NULL = 0, J_BOOL, J_NUM, J_STR, J_ARR, J_OBJ };

struct JNode {
  uint8_t  type = J_NULL;
  bool     bval = false;
  double   num = 0;
  int32_t  strOff = -1;   // 字符串在 pool 中的偏移
  int32_t  keyOff = -1;   // 对象成员名在 pool 中的偏移
  int32_t  first = -1;    // 第一个子节点
  int32_t  next = -1;     // 下一个兄弟节点
};

class JDoc {
public:
  static const int MAX_NODES = 400;
  static const int POOL_SIZE = 6144;

  bool parse(const char* text, size_t len)
  {
    count_ = 0;
    poolLen_ = 0;
    root_ = -1;
    p_ = text;
    end_ = text + len;
    if (!parseValue(&root_)) return false;
    return root_ >= 0;
  }

  int root() const { return root_; }

  const JNode& node(int i) const { return nodes_[i]; }

  const char* str(const JNode& n) const { return n.strOff >= 0 ? (pool_ + n.strOff) : ""; }
  const char* key(const JNode& n) const { return n.keyOff >= 0 ? (pool_ + n.keyOff) : ""; }

  int childCount(int i) const
  {
    int c = 0;
    for (int k = nodes_[i].first; k >= 0; k = nodes_[k].next) c++;
    return c;
  }

  int childAt(int i, int idx) const
  {
    for (int k = nodes_[i].first; k >= 0; k = nodes_[k].next) {
      if (idx-- == 0) return k;
    }
    return -1;
  }

  // 在对象 i 里找名为 k 的成员，返回其节点下标；找不到返回 -1
  int findKey(int i, const char* k) const
  {
    if (i < 0 || nodes_[i].type != J_OBJ) return -1;
    for (int c = nodes_[i].first; c >= 0; c = nodes_[c].next) {
      if (strcmp(key(nodes_[c]), k) == 0) return c;
    }
    return -1;
  }

private:
  JNode nodes_[MAX_NODES];
  char  pool_[POOL_SIZE];
  int   count_ = 0;
  int   poolLen_ = 0;
  int   root_ = -1;
  const char* p_ = nullptr;
  const char* end_ = nullptr;

  int newNode()
  {
    if (count_ >= MAX_NODES) return -1;
    int i = count_++;
    nodes_[i] = JNode();
    return i;
  }

  int poolPut(const char* s, size_t n)
  {
    if (poolLen_ + (int)n + 1 > POOL_SIZE) return -1;
    int off = poolLen_;
    memcpy(pool_ + off, s, n);
    pool_[off + n] = 0;
    poolLen_ += (int)n + 1;
    return off;
  }

  void skipWs()
  {
    while (p_ < end_ && (*p_ == ' ' || *p_ == '\t' || *p_ == '\r' || *p_ == '\n')) p_++;
  }

  bool parseString(int* off)
  {
    if (p_ >= end_ || *p_ != '"') return false;
    p_++;
    char tmp[256];
    int n = 0;
    while (p_ < end_ && *p_ != '"') {
      char c = *p_++;
      if (c == '\\' && p_ < end_) {
        char e = *p_++;
        switch (e) {
          case 'n': c = '\n'; break;
          case 't': c = '\t'; break;
          case 'r': c = '\r'; break;
          case 'b': c = '\b'; break;
          case 'f': c = '\f'; break;
          case 'u': {
            // 简化：跳过 4 位十六进制，取低字节（够用于 ASCII）
            if (end_ - p_ < 4) return false;
            char hex[5] = {0};
            memcpy(hex, p_, 4);
            p_ += 4;
            long v = strtol(hex, nullptr, 16);
            c = (char)(v & 0x7F);
            break;
          }
          default: c = e; break;
        }
      }
      if (n < (int)sizeof(tmp) - 1) tmp[n++] = c;
    }
    if (p_ >= end_) return false;
    p_++;   // 跳过结束引号
    tmp[n] = 0;
    *off = poolPut(tmp, (size_t)n);
    return *off >= 0;
  }

  bool parseValue(int* out)
  {
    skipWs();
    if (p_ >= end_) return false;
    char c = *p_;

    if (c == '{') {
      int self = newNode();
      if (self < 0) return false;
      nodes_[self].type = J_OBJ;
      *out = self;
      p_++;   // {
      skipWs();
      if (p_ < end_ && *p_ == '}') { p_++; return true; }
      while (p_ < end_) {
        skipWs();
        int koff = -1;
        if (!parseString(&koff)) return false;
        skipWs();
        if (p_ >= end_ || *p_ != ':') return false;
        p_++;
        int child = -1;
        if (!parseValue(&child)) return false;
        nodes_[child].keyOff = koff;
        // 挂到链表尾
        if (nodes_[self].first < 0) nodes_[self].first = child;
        else {
          int t = nodes_[self].first;
          while (nodes_[t].next >= 0) t = nodes_[t].next;
          nodes_[t].next = child;
        }
        skipWs();
        if (p_ < end_ && *p_ == ',') { p_++; continue; }
        if (p_ < end_ && *p_ == '}') { p_++; return true; }
        return false;
      }
      return false;
    }

    if (c == '[') {
      int self = newNode();
      if (self < 0) return false;
      nodes_[self].type = J_ARR;
      *out = self;
      p_++;   // [
      skipWs();
      if (p_ < end_ && *p_ == ']') { p_++; return true; }
      while (p_ < end_) {
        int child = -1;
        if (!parseValue(&child)) return false;
        if (nodes_[self].first < 0) nodes_[self].first = child;
        else {
          int t = nodes_[self].first;
          while (nodes_[t].next >= 0) t = nodes_[t].next;
          nodes_[t].next = child;
        }
        skipWs();
        if (p_ < end_ && *p_ == ',') { p_++; continue; }
        if (p_ < end_ && *p_ == ']') { p_++; return true; }
        return false;
      }
      return false;
    }

    if (c == '"') {
      int self = newNode();
      if (self < 0) return false;
      int off = -1;
      if (!parseString(&off)) return false;
      nodes_[self].type = J_STR;
      nodes_[self].strOff = off;
      *out = self;
      return true;
    }

    if (c == 't' || c == 'f') {
      int self = newNode();
      if (self < 0) return false;
      bool v = (c == 't');
      const char* lit = v ? "true" : "false";
      size_t n = strlen(lit);
      if ((size_t)(end_ - p_) < n) return false;
      p_ += n;
      nodes_[self].type = J_BOOL;
      nodes_[self].bval = v;
      *out = self;
      return true;
    }

    if (c == 'n') {
      int self = newNode();
      if (self < 0) return false;
      if ((size_t)(end_ - p_) < 4) return false;
      p_ += 4;
      nodes_[self].type = J_NULL;
      *out = self;
      return true;
    }

    // 数字
    {
      int self = newNode();
      if (self < 0) return false;
      char tmp[32];
      int n = 0;
      while (p_ < end_ && n < (int)sizeof(tmp) - 1) {
        char d = *p_;
        if ((d >= '0' && d <= '9') || d == '-' || d == '+' || d == '.' || d == 'e' || d == 'E') {
          tmp[n++] = d; p_++;
        } else break;
      }
      tmp[n] = 0;
      nodes_[self].type = J_NUM;
      nodes_[self].num = (n > 0) ? atof(tmp) : 0.0;
      *out = self;
      return true;
    }
  }
};
