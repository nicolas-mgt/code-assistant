package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
	"unicode/utf8"
)

func TestOversizedToolOutputs(t *testing.T) {
	large := "BEGIN" + strings.Repeat("ż🙂", maxOutputBytes/6+1) + "END"
	for _, path := range []string{"/v1/responses", "/v1/chat/completions"} {
		t.Run(path, func(t *testing.T) {
			list, output := "input", "output"
			tool := map[string]any{"type": "function_call_output", "call_id": "call_keep", "output": large}
			if path == "/v1/chat/completions" {
				list, output = "messages", "content"
				tool = map[string]any{"role": "tool", "tool_call_id": "call_keep", "content": large}
			}
			user := map[string]any{"role": "user", "content": large}
			body, _ := json.Marshal(map[string]any{"model": "assistant", "metadata": map[string]any{"exact": json.Number("9007199254740993")}, list: []any{user, tool}})
			result, count, err := trimToolOutputs(body, path)
			if err != nil || count != 1 {
				t.Fatalf("count=%d err=%v", count, err)
			}
			var parsed map[string]json.RawMessage
			json.Unmarshal(result, &parsed)
			var items []map[string]json.RawMessage
			json.Unmarshal(parsed[list], &items)
			var text, original string
			json.Unmarshal(items[1][output], &text)
			json.Unmarshal(items[0]["content"], &original)
			if original != large || !bytes.Contains(result, []byte("9007199254740993")) || !bytes.Contains(result, []byte("call_keep")) {
				t.Fatal("non-output data changed")
			}
			if !utf8.ValidString(text) || len(text) > retainedBytes+512 || !strings.HasPrefix(text, "BEGIN") || !strings.HasSuffix(text, "END") || !strings.Contains(text, "bytes omitted") {
				t.Fatal("missing head, tail, truncation marker or invalid output size/encoding")
			}
		})
	}
}

func TestNormalAndMultimodalRequestsUnchanged(t *testing.T) {
	cases := []string{
		`{ "model": "assistant", "input": "hello" }`,
		`{"input":[{"type":"function_call_output","call_id":"c","output":"OK"}]}`,
		`{"input":[{"role":"user","content":[{"type":"input_image","image_url":"data:image/png;base64,AAAA"}]}]}`,
		`{"input":[{"type":"function_call_output","output":[{"type":"input_text","text":"OK"}]}]}`,
	}
	for _, body := range cases {
		result, count, err := trimToolOutputs([]byte(body), "/v1/responses")
		if err != nil || count != 0 || string(result) != body {
			t.Fatalf("unchanged request modified: count=%d err=%v", count, err)
		}
	}
	boundary := strings.Repeat("x", maxOutputBytes)
	if shortenOutput(boundary) != boundary || len(shortenOutput(boundary+"x")) >= maxOutputBytes {
		t.Fatal("incorrect truncation threshold")
	}
}

func TestProxyPreservesErrorsAndForwardsTrimmedRequest(t *testing.T) {
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		if r.Method != "POST" || r.URL.RequestURI() != "/v1/responses?tag=a%2Fb" || r.Header.Get("Authorization") != "Bearer test-key" || int64(len(body)) != r.ContentLength {
			t.Error("request metadata not preserved")
		}
		if len(body) >= maxOutputBytes || !bytes.Contains(body, []byte("bytes omitted")) {
			t.Error("oversized output reached upstream")
		}
		w.Header().Set("Retry-After", "12")
		w.WriteHeader(429)
		io.WriteString(w, `{"error":"quota"}`)
	}))
	defer backend.Close()
	u, _ := url.Parse(backend.URL)
	body, _ := json.Marshal(map[string]any{"input": []any{map[string]any{"type": "function_call_output", "output": strings.Repeat("x", 13594545)}}})
	req := httptest.NewRequest("POST", "/v1/responses?tag=a%2Fb", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer test-key")
	rec := httptest.NewRecorder()
	newHandler(u).ServeHTTP(rec, req)
	if rec.Code != 429 || rec.Header().Get("Retry-After") != "12" || rec.Header().Get("X-AI-Gateway-Truncated-Outputs") != "1" || rec.Body.String() != `{"error":"quota"}` {
		t.Fatal("upstream error or truncation indicator lost")
	}
	bad := httptest.NewRecorder()
	newHandler(u).ServeHTTP(bad, httptest.NewRequest("POST", "/v1/responses", strings.NewReader("{")))
	if bad.Code != 400 {
		t.Fatal("invalid JSON was not rejected")
	}
}

func TestStreamingAndCancellation(t *testing.T) {
	cancelled := make(chan struct{})
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		io.WriteString(w, "data: first\n\n")
		w.(http.Flusher).Flush()
		<-r.Context().Done()
		close(cancelled)
	}))
	defer backend.Close()
	u, _ := url.Parse(backend.URL)
	guard := httptest.NewServer(newHandler(u))
	defer guard.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "POST", guard.URL+"/v1/responses", strings.NewReader(`{"input":"hello"}`))
	response, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	line, err := bufio.NewReader(response.Body).ReadString('\n')
	if err != nil || line != "data: first\n" {
		t.Fatalf("stream buffered or damaged: %q %v", line, err)
	}
	cancel()
	select {
	case <-cancelled:
	case <-time.After(time.Second):
		t.Fatal("upstream request was not cancelled")
	}
}
