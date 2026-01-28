// Package plugins provides a Lua-based plugin system for TetraCore Hub.
package plugins

import (
	"context"
	"errors"
	"sync"
	"time"

	luavm "github.com/tetra/core-hub/internal/plugins/lua"
	lua "github.com/yuin/gopher-lua"
)

// VMPool manages a pool of Lua VMs for concurrent execution.
type VMPool struct {
	vms         chan *luavm.VM
	maxExecTime time.Duration
	maxMemory   int64
	size        int
	mu          sync.Mutex
	closed      bool
}

// NewVMPool creates a new VM pool.
func NewVMPool(size int, maxExecTime time.Duration, maxMemory int64) (*VMPool, error) {
	if size < 1 {
		size = 4
	}

	pool := &VMPool{
		vms:         make(chan *luavm.VM, size),
		maxExecTime: maxExecTime,
		maxMemory:   maxMemory,
		size:        size,
	}

	// Pre-create VMs
	for i := 0; i < size; i++ {
		vm := luavm.NewVM(luavm.VMConfig{
			MaxExecTime: maxExecTime,
			MaxMemory:   maxMemory,
		})
		pool.vms <- vm
	}

	return pool, nil
}

// Get retrieves a VM from the pool.
func (p *VMPool) Get() *luavm.VM {
	return <-p.vms
}

// Put returns a VM to the pool.
func (p *VMPool) Put(vm *luavm.VM) {
	p.mu.Lock()
	if p.closed {
		p.mu.Unlock()
		vm.Close()
		return
	}
	p.mu.Unlock()

	vm.Reset()
	p.vms <- vm
}

// Close closes all VMs in the pool.
func (p *VMPool) Close() {
	p.mu.Lock()
	p.closed = true
	p.mu.Unlock()

	close(p.vms)
	for vm := range p.vms {
		vm.Close()
	}
}

// executeHook executes a hook function on a VM.
func executeHook(ctx context.Context, vm *luavm.VM, code string, hookCtx *HookContext) (*HookResult, error) {
	L := vm.GetState()

	// Load the plugin code
	if err := L.DoString(code); err != nil {
		return nil, err
	}

	// Build function name: on_<hook_type>
	funcName := "on_" + string(hookCtx.HookType)

	// Get the function
	fn := L.GetGlobal(funcName)
	if fn.Type() != lua.LTFunction {
		// Function doesn't exist, not an error
		return &HookResult{Modified: false}, nil
	}

	// Build context table
	ctxTable := L.NewTable()
	ctxTable.RawSetString("hook_type", lua.LString(hookCtx.HookType))
	ctxTable.RawSetString("user_id", lua.LString(hookCtx.UserID))
	ctxTable.RawSetString("client_id", lua.LString(hookCtx.ClientID))

	// Add data
	dataTable := L.NewTable()
	for k, v := range hookCtx.Data {
		dataTable.RawSetString(k, luavm.GoToLValue(L, v))
	}
	ctxTable.RawSetString("data", dataTable)

	// Add task if present
	if hookCtx.Task != nil {
		taskTable := buildTaskTable(L, hookCtx.Task)
		ctxTable.RawSetString("task", taskTable)
	}

	// Call function with timeout
	execCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()

	resultChan := make(chan *HookResult, 1)
	errChan := make(chan error, 1)

	go func() {
		L.Push(fn)
		L.Push(ctxTable)

		if err := L.PCall(1, 1, nil); err != nil {
			errChan <- err
			return
		}

		// Get result
		result := L.Get(-1)
		L.Pop(1)

		hookResult := &HookResult{Modified: false}

		if result.Type() == lua.LTTable {
			resultTbl := result.(*lua.LTable)

			if modified := resultTbl.RawGetString("modified"); modified.Type() == lua.LTBool {
				hookResult.Modified = bool(modified.(lua.LBool))
			}

			if abort := resultTbl.RawGetString("abort"); abort.Type() == lua.LTBool {
				hookResult.Abort = bool(abort.(lua.LBool))
			}

			if errMsg := resultTbl.RawGetString("error"); errMsg.Type() == lua.LTString {
				hookResult.Error = errMsg.String()
			}

			if data := resultTbl.RawGetString("data"); data.Type() == lua.LTTable {
				hookResult.Data = luavm.TableToMap(data.(*lua.LTable))
			}
		}

		resultChan <- hookResult
	}()

	select {
	case result := <-resultChan:
		return result, nil
	case err := <-errChan:
		return nil, err
	case <-execCtx.Done():
		return nil, errors.New("hook execution timeout")
	}
}

// ParsePluginMetadata parses plugin metadata using the VM pool.
func (p *VMPool) ParsePluginMetadata(code string) (*PluginMetadata, error) {
	vm := p.Get()
	defer p.Put(vm)

	meta, err := vm.ParsePluginMetadata(code)
	if err != nil {
		return nil, err
	}

	return &PluginMetadata{
		ID:          meta.ID,
		Name:        meta.Name,
		Version:     meta.Version,
		Author:      meta.Author,
		Description: meta.Description,
		Hooks:       convertHooks(meta.Hooks),
	}, nil
}

// PluginMetadata mirrors the lua package metadata for internal use.
type PluginMetadata struct {
	ID          string
	Name        string
	Version     string
	Author      string
	Description string
	Hooks       []HookType
}

// convertHooks converts string hooks to HookType.
func convertHooks(hooks []string) []HookType {
	result := make([]HookType, len(hooks))
	for i, h := range hooks {
		result[i] = HookType(h)
	}
	return result
}

// buildTaskTable creates a Lua table from a task.
func buildTaskTable(L *lua.LState, task interface{}) *lua.LTable {
	tbl := L.NewTable()

	// Type assert and extract task fields
	// This is a simplified version - you'd expand this based on your Task struct
	if t, ok := task.(interface{ ToMap() map[string]any }); ok {
		taskMap := t.ToMap()
		for k, v := range taskMap {
			tbl.RawSetString(k, luavm.GoToLValue(L, v))
		}
	}

	return tbl
}
