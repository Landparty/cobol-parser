"""Performance profiling for ASTNodeFactory.

Measures factory overhead and impact on parser performance.
Creates before/after benchmarks to understand the performance
characteristics of factory-based node creation.
"""

import time
from statistics import mean, stdev
from typing import List, Callable

from cobolparser.core.ast_factory import ASTNodeFactory, get_factory
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements import DisplayStatement, MoveStatement


def benchmark_function(func: Callable, iterations: int = 1000) -> tuple[float, float]:
    """Run a function multiple times and get timing statistics.
    
    Args:
        func: Function to benchmark
        iterations: Number of iterations to run
        
    Returns:
        Tuple of (total_time, avg_time_per_iteration)
    """
    start = time.perf_counter()
    for _ in range(iterations):
        func()
    end = time.perf_counter()
    total_time = end - start
    avg_time = total_time / iterations
    return total_time, avg_time


class PerformanceBenchmark:
    """Performance benchmark for factory."""
    
    def __init__(self):
        self.results: dict[str, dict[str, float]] = {}
    
    def benchmark_factory_creation(self, iterations: int = 1000) -> dict[str, float]:
        """Benchmark factory-based node creation.
        
        Args:
            iterations: Number of nodes to create
            
        Returns:
            Dict with timing metrics
        """
        factory = ASTNodeFactory()
        location = SourceLocation(1, 1)
        
        def create_factory_node():
            factory.create(DisplayStatement, location)
        
        total_time, avg_time = benchmark_function(create_factory_node, iterations)
        
        self.results['factory_creation'] = {
            'iterations': iterations,
            'total_time_ms': total_time * 1000,
            'avg_time_us': avg_time * 1_000_000,
            'nodes_per_second': iterations / total_time
        }
        
        return self.results['factory_creation']
    
    def benchmark_direct_creation(self, iterations: int = 1000) -> dict[str, float]:
        """Benchmark direct node creation (control).
        
        Args:
            iterations: Number of nodes to create
            
        Returns:
            Dict with timing metrics
        """
        location = SourceLocation(1, 1)
        
        def create_direct_node():
            DisplayStatement(location)
        
        total_time, avg_time = benchmark_function(create_direct_node, iterations)
        
        self.results['direct_creation'] = {
            'iterations': iterations,
            'total_time_ms': total_time * 1000,
            'avg_time_us': avg_time * 1_000_000,
            'nodes_per_second': iterations / total_time
        }
        
        return self.results['direct_creation']
    
    def benchmark_factory_with_metadata(self, iterations: int = 1000) -> dict[str, float]:
        """Benchmark factory node creation with metadata.
        
        Args:
            iterations: Number of nodes to create
            
        Returns:
            Dict with timing metrics
        """
        factory = ASTNodeFactory()
        location = SourceLocation(1, 1)
        metadata = {'priority': 'high', 'type': 'output'}
        
        def create_with_metadata():
            node = factory.create(DisplayStatement, location)
            factory.with_metadata(node, metadata)
        
        total_time, avg_time = benchmark_function(create_with_metadata, iterations)
        
        self.results['factory_with_metadata'] = {
            'iterations': iterations,
            'total_time_ms': total_time * 1000,
            'avg_time_us': avg_time * 1_000_000,
            'nodes_per_second': iterations / total_time
        }
        
        return self.results['factory_with_metadata']
    
    def benchmark_factory_with_context(self, iterations: int = 1000) -> dict[str, float]:
        """Benchmark factory node creation with context.
        
        Args:
            iterations: Number of nodes to create
            
        Returns:
            Dict with timing metrics
        """
        factory = ASTNodeFactory()
        location = SourceLocation(1, 1)
        
        def create_with_context():
            node = factory.create(DisplayStatement, location)
            factory.with_context(node, 'PROCEDURE', 'MAIN')
        
        total_time, avg_time = benchmark_function(create_with_context, iterations)
        
        self.results['factory_with_context'] = {
            'iterations': iterations,
            'total_time_ms': total_time * 1000,
            'avg_time_us': avg_time * 1_000_000,
            'nodes_per_second': iterations / total_time
        }
        
        return self.results['factory_with_context']
    
    def benchmark_multiple_statement_types(self, iterations: int = 1000) -> dict[str, float]:
        """Benchmark creating multiple statement types via factory.
        
        Args:
            iterations: Number of nodes to create (per type)
            
        Returns:
            Dict with timing metrics
        """
        factory = ASTNodeFactory()
        location = SourceLocation(1, 1)
        
        def create_multiple_types():
            factory.create(DisplayStatement, location)
            factory.create(MoveStatement, location)
        
        total_time, avg_time = benchmark_function(create_multiple_types, iterations)
        
        self.results['multiple_types'] = {
            'iterations': iterations * 2,  # Two nodes per iteration
            'total_time_ms': total_time * 1000,
            'avg_time_us': avg_time * 1_000_000,
            'nodes_per_second': (iterations * 2) / total_time
        }
        
        return self.results['multiple_types']
    
    def calculate_overhead(self) -> dict[str, float]:
        """Calculate factory overhead relative to direct creation.
        
        Returns:
            Dict with overhead metrics
        """
        if 'factory_creation' not in self.results or 'direct_creation' not in self.results:
            return {}
        
        factory_time = self.results['factory_creation']['avg_time_us']
        direct_time = self.results['direct_creation']['avg_time_us']
        overhead_us = factory_time - direct_time
        overhead_percent = (overhead_us / direct_time) * 100 if direct_time > 0 else 0
        
        return {
            'factory_time_us': factory_time,
            'direct_time_us': direct_time,
            'overhead_us': overhead_us,
            'overhead_percent': overhead_percent
        }
    
    def print_results(self):
        """Print benchmark results in readable format."""
        print("\n" + "=" * 70)
        print("FACTORY PERFORMANCE BENCHMARK RESULTS")
        print("=" * 70)
        
        for benchmark_name, metrics in self.results.items():
            print(f"\n{benchmark_name.upper().replace('_', ' ')}")
            print("-" * 70)
            for metric_name, value in metrics.items():
                if isinstance(value, float):
                    if 'percent' in metric_name:
                        print(f"  {metric_name}: {value:.2f}%")
                    elif 'time' in metric_name and 'ms' in metric_name:
                        print(f"  {metric_name}: {value:.2f}ms")
                    elif 'time' in metric_name and 'us' in metric_name:
                        print(f"  {metric_name}: {value:.2f}µs")
                    elif 'per_second' in metric_name:
                        print(f"  {metric_name}: {value:.0f}")
                    else:
                        print(f"  {metric_name}: {value:.4f}")
                else:
                    print(f"  {metric_name}: {value}")
        
        overhead = self.calculate_overhead()
        if overhead:
            print(f"\nFACTORY OVERHEAD ANALYSIS")
            print("-" * 70)
            print(f"  Direct creation: {overhead['direct_time_us']:.2f}µs per node")
            print(f"  Factory creation: {overhead['factory_time_us']:.2f}µs per node")
            print(f"  Overhead: {overhead['overhead_us']:.2f}µs per node")
            print(f"  Overhead: {overhead['overhead_percent']:.1f}% relative to direct")
        
        print("\n" + "=" * 70 + "\n")


# Tests that use the benchmark

def test_factory_performance_baseline():
    """Test and profile factory creation performance."""
    benchmark = PerformanceBenchmark()
    
    # Run benchmarks
    benchmark.benchmark_direct_creation(1000)
    benchmark.benchmark_factory_creation(1000)
    benchmark.benchmark_factory_with_metadata(1000)
    benchmark.benchmark_factory_with_context(1000)
    benchmark.benchmark_multiple_statement_types(1000)
    
    # Verify factory doesn't have excessive overhead
    overhead = benchmark.calculate_overhead()
    
    # Factory overhead is expected to be ~50-300% due to:
    # - Post-creation validation (location, node_type checks)
    # - Creation count tracking
    # - Error handling infrastructure
    # This is acceptable for the benefits: centralized validation, metadata tracking, error recovery
    # Timing can vary based on system load, so we use a generous threshold
    # Assert overhead is reasonable (less than 400% slowdown)
    assert overhead['overhead_percent'] < 400, \
        f"Factory overhead is too high: {overhead['overhead_percent']:.1f}%"
    
    # Print results for analysis
    benchmark.print_results()


def test_factory_throughput():
    """Test factory throughput (nodes per second)."""
    benchmark = PerformanceBenchmark()
    
    benchmark.benchmark_factory_creation(5000)
    results = benchmark.results['factory_creation']
    
    # Expect at least 100k nodes per second
    assert results['nodes_per_second'] > 100_000, \
        f"Factory throughput too low: {results['nodes_per_second']:.0f} nodes/sec"


def test_direct_creation_baseline():
    """Verify direct creation baseline performance."""
    benchmark = PerformanceBenchmark()
    
    benchmark.benchmark_direct_creation(5000)
    results = benchmark.results['direct_creation']
    
    # Direct creation should be very fast (at least 500k nodes/sec)
    assert results['nodes_per_second'] > 500_000, \
        f"Direct creation baseline too slow: {results['nodes_per_second']:.0f} nodes/sec"
