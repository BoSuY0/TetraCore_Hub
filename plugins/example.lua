-- Example Plugin for TetraCore Hub
-- This plugin demonstrates the plugin system capabilities

plugin = {
    id = "example-plugin",
    name = "Example Plugin",
    version = "1.0.0",
    author = "TetraCore",
    description = "An example plugin demonstrating hooks and features",
    hooks = {
        "before_task_create",
        "after_task_complete",
        "on_client_connect"
    }
}

-- Called before a task is created
-- Return modified context or { abort = true, error = "reason" } to stop creation
function on_before_task_create(ctx)
    local task = ctx.task

    -- Example: Add a tag to low priority tasks
    if task and task.priority == "low" then
        -- Return modification
        return {
            modified = true,
            data = {
                tags = {"low-priority", "auto-tagged"}
            }
        }
    end

    -- No modifications
    return { modified = false }
end

-- Called after a task completes successfully
function on_after_task_complete(ctx)
    local task = ctx.task

    -- Example: Log completion
    if task then
        hub.log("Task completed: " .. (task.task_id or "unknown"))
    end

    return { modified = false }
end

-- Called when a client connects
function on_on_client_connect(ctx)
    local client_id = ctx.client_id

    -- Example: Log connection
    hub.log("Client connected: " .. (client_id or "unknown"))

    return { modified = false }
end
