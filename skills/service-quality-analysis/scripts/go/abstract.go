// abstract counts top-level type declarations and interfaces per package directory.
package main

import (
	"encoding/json"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
)

type counts struct {
	Types  int `json:"types"`
	Ifaces int `json:"ifaces"`
}

func main() {
	root := os.Args[1]
	out := map[string]*counts{}
	fset := token.NewFileSet()
	filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		name := d.Name()
		if d.IsDir() {
			if name == "node_modules" || name == "testdata" || name == "vendor" || (strings.HasPrefix(name, ".") && path != root) {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			return nil
		}
		f, perr := parser.ParseFile(fset, path, nil, parser.SkipObjectResolution)
		if perr != nil {
			return nil
		}
		rel, _ := filepath.Rel(root, filepath.Dir(path))
		if rel == "." {
			rel = "(root)"
		}
		c := out[rel]
		if c == nil {
			c = &counts{}
			out[rel] = c
		}
		for _, decl := range f.Decls {
			gd, ok := decl.(*ast.GenDecl)
			if !ok || gd.Tok != token.TYPE {
				continue
			}
			for _, spec := range gd.Specs {
				ts := spec.(*ast.TypeSpec)
				c.Types++
				if _, ok := ts.Type.(*ast.InterfaceType); ok {
					c.Ifaces++
				}
			}
		}
		return nil
	})
	json.NewEncoder(os.Stdout).Encode(out)
}
