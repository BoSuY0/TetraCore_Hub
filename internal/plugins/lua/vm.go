// Package lua provides Lua VM management for the plugin system.
package lua

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	lua "github.com/yuin/gopher-lua"
)

// VM wraps a Lua state with sandboxing and timeout support.
type VM struct {
	state       *lua.LState
	maxExecTime time.Duration
	maxMemory   int64
	mu          sync.Mutex
}

// PluginMetadata contains parsed plugin information.
type PluginMetadata struct {
	ID          string
	Name        string
	Version     string
	Author      string
	Description string
	Hooks       []string
}

// VMConfig holds VM configuration.
type VMConfig struct {
	MaxExecTime time.Duration
	MaxMemory   int64
}

// DefaultVMConfig returns default VM configuration.
func DefaultVMConfig() VMConfig {
	return VMConfig{
		MaxExecTime: 5 * time.Second,
		MaxMemory:   64 * 1024 * 1024,
	}
}

// NewVM creates a new sandboxed Lua VM.
func NewVM(cfg VMConfig) *VM {
	state := lua.NewState(lua.Options{
		SkipOpenLibs: true,
	})

	// Load safe libraries
	lua.OpenBase(state)
	lua.OpenTable(state)
	lua.OpenString(state)
	lua.OpenMath(state)

	// Remove dangerous functions
	state.SetGlobal("dofile", lua.LNil)
	state.SetGlobal("loadfile", lua.LNil)
	state.SetGlobal("load", lua.LNil)
	state.SetGlobal("loadstring", lua.LNil)

	return &VM{
		state:       state,
		maxExecTime: cfg.MaxExecTime,
		maxMemory:   cfg.MaxMemory,
	}
}

// Close closes the VM.
func (vm *VM) Close() {
	vm.mu.Lock()
	defer vm.mu.Unlock()
	vm.state.Close()
}

// Reset resets the VM state.
func (vm *VM) Reset() {
	vm.mu.Lock()
	defer vm.mu.Unlock()

	// Clear globals
	vm.state.SetTop(0)
}

// Execute executes Lua code with timeout.
func (vm *VM) Execute(ctx context.Context, code string) error {
	vm.mu.Lock()
	defer vm.mu.Unlock()

	// Create cancellation context
	execCtx, cancel := context.WithTimeout(ctx, vm.maxExecTime)
	defer cancel()

	// Set up timeout
	done := make(chan error, 1)
	go func() {
		done <- vm.state.DoString(code)
	}()

	select {
	case err := <-done:
		return err
	case <-execCtx.Done():
		vm.state.Close()
		vm.state = lua.NewState()
		return errors.New("execution timeout")
	}
}

// ParsePluginMetadata parses plugin metadata from Lua source.
func (vm *VM) ParsePluginMetadata(code string) (*PluginMetadata, error) {
	vm.mu.Lock()
	defer vm.mu.Unlock()

	if err := vm.state.DoString(code); err != nil {
		return nil, fmt.Errorf("failed to parse plugin: %w", err)
	}

	// Get plugin table
	pluginTable := vm.state.GetGlobal("plugin")
	if pluginTable.Type() != lua.LTTable {
		return nil, errors.New("plugin table not found")
	}

	tbl := pluginTable.(*lua.LTable)
	metadata := &PluginMetadata{}

	// Extract fields
	if name := tbl.RawGetString("name"); name.Type() == lua.LTString {
		metadata.Name = name.String()
		metadata.ID = name.String() // Use name as ID if not specified
	}
	if id := tbl.RawGetString("id"); id.Type() == lua.LTString {
		metadata.ID = id.String()
	}
	if version := tbl.RawGetString("version"); version.Type() == lua.LTString {
		metadata.Version = version.String()
	}
	if author := tbl.RawGetString("author"); author.Type() == lua.LTString {
		metadata.Author = author.String()
	}
	if desc := tbl.RawGetString("description"); desc.Type() == lua.LTString {
		metadata.Description = desc.String()
	}

	// Extract hooks
	if hooks := tbl.RawGetString("hooks"); hooks.Type() == lua.LTTable {
		hooksTbl := hooks.(*lua.LTable)
		hooksTbl.ForEach(func(_, v lua.LValue) {
			if v.Type() == lua.LTString {
				metadata.Hooks = append(metadata.Hooks, v.String())
			}
		})
	}

	if metadata.Name == "" {
		return nil, errors.New("plugin name is required")
	}

	return metadata, nil
}

// CallFunction calls a Lua function with arguments.
func (vm *VM) CallFunction(ctx context.Context, code, funcName string, args ...lua.LValue) ([]lua.LValue, error) {
	vm.mu.Lock()
	defer vm.mu.Unlock()

	// Load code
	if err := vm.state.DoString(code); err != nil {
		return nil, fmt.Errorf("failed to load code: %w", err)
	}

	// Get function
	fn := vm.state.GetGlobal(funcName)
	if fn.Type() != lua.LTFunction {
		return nil, nil // Function doesn't exist, not an error
	}

	// Create cancellation context
	execCtx, cancel := context.WithTimeout(ctx, vm.maxExecTime)
	defer cancel()

	// Call function
	errChan := make(chan error, 1)
	resultChan := make(chan []lua.LValue, 1)

	go func() {
		// Push function and args
		vm.state.Push(fn)
		for _, arg := range args {
			vm.state.Push(arg)
		}

		// Call
		err := vm.state.PCall(len(args), lua.MultRet, nil)
		if err != nil {
			errChan <- err
			return
		}

		// Get results
		top := vm.state.GetTop()
		results := make([]lua.LValue, top)
		for i := 1; i <= top; i++ {
			results[i-1] = vm.state.Get(i)
		}
		vm.state.SetTop(0)
		resultChan <- results
	}()

	select {
	case err := <-errChan:
		return nil, err
	case results := <-resultChan:
		return results, nil
	case <-execCtx.Done():
		return nil, errors.New("execution timeout")
	}
}

// SetGlobal sets a global variable.
func (vm *VM) SetGlobal(name string, value lua.LValue) {
	vm.mu.Lock()
	defer vm.mu.Unlock()
	vm.state.SetGlobal(name, value)
}

// GetState returns the underlying Lua state.
func (vm *VM) GetState() *lua.LState {
	return vm.state
}

// TableToMap converts a Lua table to a Go map.
func TableToMap(tbl *lua.LTable) map[string]any {
	result := make(map[string]any)
	tbl.ForEach(func(k, v lua.LValue) {
		key := k.String()
		result[key] = LValueToGo(v)
	})
	return result
}

// LValueToGo converts a Lua value to a Go value.
func LValueToGo(v lua.LValue) any {
	switch val := v.(type) {
	case lua.LBool:
		return bool(val)
	case lua.LNumber:
		return float64(val)
	case lua.LString:
		return string(val)
	case *lua.LTable:
		return TableToMap(val)
	case *lua.LNilType:
		return nil
	default:
		return v.String()
	}
}

// GoToLValue converts a Go value to a Lua value.
func GoToLValue(L *lua.LState, v any) lua.LValue {
	switch val := v.(type) {
	case bool:
		return lua.LBool(val)
	case int:
		return lua.LNumber(val)
	case int64:
		return lua.LNumber(val)
	case float64:
		return lua.LNumber(val)
	case string:
		return lua.LString(val)
	case map[string]any:
		return MapToTable(L, val)
	case []any:
		return SliceToTable(L, val)
	case nil:
		return lua.LNil
	default:
		return lua.LString(fmt.Sprintf("%v", v))
	}
}

// MapToTable converts a Go map to a Lua table.
func MapToTable(L *lua.LState, m map[string]any) *lua.LTable {
	tbl := L.NewTable()
	for k, v := range m {
		tbl.RawSetString(k, GoToLValue(L, v))
	}
	return tbl
}

// SliceToTable converts a Go slice to a Lua table.
func SliceToTable(L *lua.LState, s []any) *lua.LTable {
	tbl := L.NewTable()
	for i, v := range s {
		tbl.RawSetInt(i+1, GoToLValue(L, v))
	}
	return tbl
}
