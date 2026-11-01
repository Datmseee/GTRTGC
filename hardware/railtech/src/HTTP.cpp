#include "HttpConfiguration.h"
#include <HTTPClient.h>    // also built into the core [76]

String httpGET(const char* url) {
  HTTPClient http;
  http.begin(url);
  int code = http.GET();
  String payload = (code > 0) ? http.getString() : "";
  Serial.printf("GET %s -> %d\n", url, code);
  http.end();
  return payload;
}