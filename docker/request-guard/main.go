package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strconv"
	"time"
	"unicode/utf8"
)

const maxOutputBytes = 10 * 1024 * 1024
const retainedBytes = 256 * 1024

func shortenOutput(text string) string {
	if len(text) <= maxOutputBytes {
		return text
	}
	head := retainedBytes / 2
	for !utf8.RuneStart(text[head]) {
		head--
	}
	tail := len(text) - retainedBytes/2
	for !utf8.RuneStart(text[tail]) {
		tail++
	}
	marker := fmt.Sprintf("\n\n[AI Gateway: oversized tool output truncated; %d of %d UTF-8 bytes omitted. Beginning and end retained. Do not infer contents of the omitted section; request a narrower tool result if needed.]\n\n", tail-head, len(text))
	return text[:head] + marker + text[tail:]
}

func trimToolOutputs(body []byte, path string) ([]byte, int, error) {
	var request map[string]json.RawMessage
	if err := json.Unmarshal(body, &request); err != nil {
		return nil, 0, err
	}
	listKey, kindKey, kind, outputKey := "input", "type", "function_call_output", "output"
	if path == "/v1/chat/completions" {
		listKey, kindKey, kind, outputKey = "messages", "role", "tool", "content"
	}
	list := bytes.TrimSpace(request[listKey])
	if len(list) == 0 || list[0] != '[' {
		return body, 0, nil
	}
	var items []map[string]json.RawMessage
	if err := json.Unmarshal(list, &items); err != nil {
		return nil, 0, err
	}
	changed := 0
	for _, item := range items {
		var itemKind string
		if json.Unmarshal(item[kindKey], &itemKind) != nil || itemKind != kind {
			continue
		}
		output := bytes.TrimSpace(item[outputKey])
		if len(output) == 0 || output[0] != '"' {
			continue
		}
		var text string
		if err := json.Unmarshal(output, &text); err != nil {
			return nil, 0, err
		}
		if len(text) > maxOutputBytes {
			item[outputKey], _ = json.Marshal(shortenOutput(text))
			changed++
		}
	}
	if changed == 0 {
		return body, 0, nil
	}
	var err error
	request[listKey], err = json.Marshal(items)
	if err != nil {
		return nil, 0, err
	}
	result, err := json.Marshal(request)
	return result, changed, err
}

func newHandler(upstream *url.URL) http.Handler {
	proxy := httputil.NewSingleHostReverseProxy(upstream)
	proxy.FlushInterval = -1
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost && (r.URL.Path == "/v1/responses" || r.URL.Path == "/v1/chat/completions") {
			body, err := io.ReadAll(r.Body)
			r.Body.Close()
			if err != nil {
				http.Error(w, "AI Gateway: could not read request body", http.StatusBadRequest)
				return
			}
			body, count, err := trimToolOutputs(body, r.URL.Path)
			if err != nil {
				http.Error(w, "AI Gateway: invalid JSON request", http.StatusBadRequest)
				return
			}
			if count > 0 {
				log.Printf("shortened %d oversized tool output(s)", count)
				w.Header().Set("X-AI-Gateway-Truncated-Outputs", strconv.Itoa(count))
			}
			r.Body = io.NopCloser(bytes.NewReader(body))
			r.ContentLength = int64(len(body))
			r.Header.Del("Content-Length")
			r.TransferEncoding = nil
		}
		proxy.ServeHTTP(w, r)
	})
}

func main() {
	upstream, err := url.Parse("http://127.0.0.1:8317")
	if err != nil {
		log.Fatal(err)
	}
	server := &http.Server{Addr: ":8318", Handler: newHandler(upstream), ReadHeaderTimeout: 10 * time.Second}
	log.Fatal(server.ListenAndServe())
}
