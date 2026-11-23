//! Fresh-process controls for empty-child transaction storage. The timed work is
//! protocol preparation only; it does not measure IPC, GPUI, paint or input.
use bun_native_protocol::{Element, NodeId, Operation, Style, Tree};
use std::hint::black_box;
use std::sync::{Arc, Barrier};
use std::time::Instant;

fn id(n: u64) -> NodeId {
    NodeId::try_from(n).unwrap()
}

fn operations(n: usize, grouped: bool) -> Vec<Operation> {
    let mut result = Vec::with_capacity(n * 2);
    for i in 0..n {
        let (parent_id, index) = if !grouped {
            (id(1), i)
        } else if i % 4 == 0 {
            (id(1), i / 4)
        } else {
            (id((i - i % 4) as u64 + 2), i % 4 - 1)
        };
        let element = if grouped && i % 4 == 0 {
            Element::Box {
                accessibility: Default::default(),
                style: Style::default(),
            }
        } else {
            Element::Text {
                accessible_live: None,
                text: "x".into(),
                style: Style::default(),
            }
        };
        let node_id = id(i as u64 + 2);
        result.push(Operation::Create { node_id, element });
        result.push(Operation::Insert {
            parent_id,
            child_id: node_id,
            index,
        });
    }
    result
}

fn main() {
    for grouped in [false, true] {
        for n in [1, 16, 128, 1024] {
            let iterations = if n == 1024 { 100 } else { 300 };
            let mut elapsed = 0u128;
            black_box(
                Tree::new(id(1))
                    .prepare(0, operations(n, grouped), 1)
                    .unwrap(),
            );
            for _ in 0..iterations {
                let tree = Tree::new(id(1));
                let operations = operations(n, grouped);
                let start = Instant::now();
                let result = black_box(tree.prepare(0, operations, 1).unwrap());
                elapsed += start.elapsed().as_nanos();
                assert_eq!(result.tree.nodes().len(), n + 1);
            }
            println!(
                "{}",
                serde_json::json!({"kind":"prepare", "shape":if grouped {"grouped"} else {"flat"}, "nodes":n, "iterations":iterations, "elapsed_ns":elapsed})
            );
        }
    }
    // Independent trees on different threads expose shared-refcount contention.
    // This includes setup and allocation and is a guard, not a UI workload.
    for threads in [1, 2, 4] {
        let barrier = Arc::new(Barrier::new(threads + 1));
        let workers: Vec<_> = (0..threads)
            .map(|_| {
                let barrier = barrier.clone();
                std::thread::spawn(move || {
                    black_box(
                        Tree::new(id(1))
                            .prepare(0, operations(128, false), 1)
                            .unwrap(),
                    );
                    barrier.wait();
                    for _ in 0..1000 {
                        let result = black_box(
                            Tree::new(id(1))
                                .prepare(0, operations(128, false), 1)
                                .unwrap(),
                        );
                        assert_eq!(result.tree.nodes().len(), 129);
                    }
                })
            })
            .collect();
        let start = Instant::now();
        barrier.wait();
        for worker in workers {
            worker.join().unwrap();
        }
        println!(
            "{}",
            serde_json::json!({"kind":"concurrent", "threads":threads, "iterations_per_thread":1000, "nodes":128, "elapsed_ns":start.elapsed().as_nanos()})
        );
    }
}
