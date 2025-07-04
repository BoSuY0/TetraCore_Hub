export interface StreamHubHealth {
  status: string;
  timestamp: string;
  version: string;
  uptime: number;
  components: {
    redis: boolean;
    client_manager: boolean;
    task_router: boolean;
    websocket_manager: boolean;
    health_monitor: boolean;
    metrics_collector: boolean;
  };
}

export interface StreamHubMetrics {
  timestamp: string;
  system: {
    cpu_usage: number;
    memory_usage: number;
    disk_usage: number;
    uptime: number;
  };
  hub: {
    total_connections: number;
    active_clients: number;
    total_tasks_processed: number;
    tasks_per_second: number;
    average_response_time: number;
    error_rate: number;
  };
  redis: {
    connected: boolean;
    memory_usage: string;
    commands_processed: number;
    hits: number;
    misses: number;
  };
}

export interface Client {
  client_id: string;
  client_name: string;
  client_type: 'bot' | 'worker' | 'worker_api' | 'stream_hub' | 'monitor' | 'admin';
  client_version: string;
  connection_status: 'connected' | 'disconnected' | 'connecting' | 'reconnecting' | 'error';
  worker_status?: 'idle' | 'busy' | 'overloaded' | 'maintenance' | 'error';
  capabilities?: string[];
  max_concurrent_tasks?: number;
  current_load?: number;
  session_id?: string;
  connected_at?: string;
  last_ping?: string;
  last_activity?: string;
  remote_address?: string;
  uptime?: number;
  active_tasks_count?: number;
  is_healthy?: boolean;
  stats: {
    total_tasks?: number;
    successful_tasks?: number;
    failed_tasks?: number;
    timeout_tasks?: number;
    active_tasks?: number;
    average_processing_time?: number;
    last_activity?: string;
    connected_at?: string;
    total_connection_time?: number;
    disconnection_count?: number;
    error_stats?: Record<string, number>;
    resource_usage?: Record<string, number>;
  };
}

export interface Task {
  task_id: string;
  task_type: string;
  status: 'pending' | 'assigned' | 'processing' | 'completed' | 'failed' | 'timeout' | 'retry' | 'cancelled';
  priority: 'low' | 'normal' | 'high' | 'critical';
  created_at: string;
  started_at?: string;
  completed_at?: string;
  assigned_worker?: string;
  retry_count: number;
  max_retries: number;
  timeout: number;
  execution_time?: number;
  error_message?: string;
  task_data?: Record<string, any>;
}

export interface TaskQueueStats {
  total_tasks: number;
  pending_tasks: number;
  processing_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  average_processing_time: number;
  queue_sizes: {
    critical?: number;
    high: number;
    normal: number;
    low: number;
  };
  worker_distribution: Record<string, number>;
}

export interface ClientsResponse {
  clients: Client[];
  total_count: number;
}

export interface WebSocketMessage {
  message_id: string;
  message_type: string;
  timestamp: string;
  sender_id?: string;
  recipient_id?: string;
  correlation_id?: string;
  data?: Record<string, any>;
}

export interface SystemAlert {
  id: string;
  type: 'info' | 'warning' | 'error' | 'success';
  title: string;
  message: string;
  timestamp: string;
  acknowledged: boolean;
  source: string;
}

export interface ConnectionStats {
  total_connections: number;
  active_connections: number;
  peak_connections: number;
  connection_rate: number;
  disconnection_rate: number;
  average_session_duration: number;
}

export interface PerformanceMetrics {
  requests_per_second: number;
  average_response_time: number;
  error_rate: number;
  success_rate: number;
  peak_memory_usage: number;
  cpu_usage_history: Array<{
    timestamp: string;
    value: number;
  }>;
  memory_usage_history: Array<{
    timestamp: string;
    value: number;
  }>;
}

export interface ApiResponse<T> {
  data?: T;
  error?: {
    code: string;
    message: string;
    details?: Record<string, any>;
  };
  timestamp: string;
  status: 'success' | 'error';
}

export interface DashboardData {
  health: StreamHubHealth;
  metrics: StreamHubMetrics;
  clients: ClientsResponse;
  tasks: TaskQueueStats;
  alerts: SystemAlert[];
  performance: PerformanceMetrics;
}
