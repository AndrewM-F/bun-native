//! Distinguish an immediately ready command from an actual receiver suspension.

use std::future::{Future, poll_fn};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Wake, Waker};
use std::time::Instant;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct WakeObservation {
    pub(crate) first: Instant,
    pub(crate) last: Instant,
    pub(crate) count: u64,
    pub(crate) resumed: Instant,
}

#[derive(Default)]
struct Wakes {
    first: Option<Instant>,
    last: Option<Instant>,
    count: u64,
}

struct RecordingWake {
    inner: Waker,
    events: Arc<Mutex<Wakes>>,
    wake_run_loop: bool,
}

// Diagnostic-only intervention: run after the GPUI waker has enqueued its
// runnable. The result says nothing about whether the run loop was asleep.
#[cfg(target_os = "macos")]
fn wake_main_run_loop() {
    if let Some(run_loop) = objc2_core_foundation::CFRunLoop::main() {
        run_loop.wake_up();
    }
}

#[cfg(not(target_os = "macos"))]
fn wake_main_run_loop() {}

impl Wake for RecordingWake {
    fn wake(self: Arc<Self>) {
        self.wake_by_ref();
    }

    fn wake_by_ref(self: &Arc<Self>) {
        let at = Instant::now();
        {
            let mut events = self
                .events
                .lock()
                .unwrap_or_else(|error| error.into_inner());
            events.first.get_or_insert(at);
            events.last = Some(at);
            events.count = events.count.saturating_add(1);
        }
        self.inner.wake_by_ref();
        if self.wake_run_loop {
            wake_main_run_loop();
        }
    }
}

pub(crate) async fn receive<T>(
    receiver: &async_channel::Receiver<T>,
) -> Result<(T, bool, Option<WakeObservation>), async_channel::RecvError> {
    let mut suspended = false;
    let mut receive = std::pin::pin!(receiver.recv());
    let events = crate::phases::enabled().then(|| Arc::new(Mutex::new(Wakes::default())));
    let wake_run_loop = events.is_some()
        && std::env::var_os("BUN_NATIVE_DIAGNOSTIC_RUNLOOP_WAKE").is_some_and(|value| value == "1");
    poll_fn(|cx| {
        let resumed = events.as_ref().map(|_| Instant::now());
        let result = if let Some(events) = &events {
            let waker = Waker::from(Arc::new(RecordingWake {
                inner: cx.waker().clone(),
                events: events.clone(),
                wake_run_loop,
            }));
            receive.as_mut().poll(&mut Context::from_waker(&waker))
        } else {
            receive.as_mut().poll(cx)
        };
        match result {
            Poll::Pending => {
                suspended = true;
                Poll::Pending
            }
            Poll::Ready(result) => {
                let observation = events.as_ref().and_then(|events| {
                    let events = events.lock().unwrap_or_else(|error| error.into_inner());
                    Some(WakeObservation {
                        first: events.first?,
                        last: events.last?,
                        count: events.count,
                        resumed: resumed?,
                    })
                });
                Poll::Ready(result.map(|value| (value, suspended, observation)))
            }
        }
    })
    .await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn distinguishes_ready_and_suspended_receives() {
        let (sender, receiver) = async_channel::bounded(2);
        sender.try_send(1).unwrap();
        assert_eq!(
            futures_lite::future::block_on(receive(&receiver)),
            Ok((1, false, None))
        );

        let mut future = std::pin::pin!(receive(&receiver));
        let mut context = Context::from_waker(Waker::noop());
        assert!(future.as_mut().poll(&mut context).is_pending());
        sender.try_send(2).unwrap();
        assert_eq!(
            future.as_mut().poll(&mut context),
            Poll::Ready(Ok((2, true, None)))
        );
    }

    #[test]
    fn diagnostic_waker_records_and_forwards_each_wake() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        struct Counter(AtomicUsize);
        impl Wake for Counter {
            fn wake(self: Arc<Self>) {
                self.0.fetch_add(1, Ordering::SeqCst);
            }
            fn wake_by_ref(self: &Arc<Self>) {
                self.0.fetch_add(1, Ordering::SeqCst);
            }
        }
        let counter = Arc::new(Counter(AtomicUsize::new(0)));
        let events = Arc::new(Mutex::new(Wakes::default()));
        let waker = Waker::from(Arc::new(RecordingWake {
            inner: Waker::from(counter.clone()),
            events: events.clone(),
            wake_run_loop: false,
        }));
        waker.wake_by_ref();
        waker.wake();
        let recorded = events.lock().unwrap();
        assert_eq!(recorded.count, 2);
        assert!(recorded.first.unwrap() <= recorded.last.unwrap());
        assert_eq!(counter.0.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn reports_closed_channel() {
        let (sender, receiver) = async_channel::bounded::<()>(1);
        drop(sender);
        assert!(futures_lite::future::block_on(receive(&receiver)).is_err());
    }

    #[test]
    fn reports_closure_after_suspending() {
        let (sender, receiver) = async_channel::bounded::<()>(1);
        let mut future = std::pin::pin!(receive(&receiver));
        let mut context = Context::from_waker(Waker::noop());
        assert!(future.as_mut().poll(&mut context).is_pending());
        drop(sender);
        assert!(matches!(
            future.as_mut().poll(&mut context),
            Poll::Ready(Err(_))
        ));
    }
}
