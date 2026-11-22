//! Distinguish an immediately ready command from an actual receiver suspension.

use std::future::{Future, poll_fn};
use std::task::Poll;

pub(crate) async fn receive<T>(
    receiver: &async_channel::Receiver<T>,
) -> Result<(T, bool), async_channel::RecvError> {
    let mut suspended = false;
    let mut receive = std::pin::pin!(receiver.recv());
    poll_fn(|cx| match receive.as_mut().poll(cx) {
        Poll::Pending => {
            suspended = true;
            Poll::Pending
        }
        Poll::Ready(result) => Poll::Ready(result.map(|value| (value, suspended))),
    })
    .await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::task::{Context, Waker};

    #[test]
    fn distinguishes_ready_and_suspended_receives() {
        let (sender, receiver) = async_channel::bounded(2);
        sender.try_send(1).unwrap();
        assert_eq!(
            futures_lite::future::block_on(receive(&receiver)),
            Ok((1, false))
        );

        let mut future = std::pin::pin!(receive(&receiver));
        let mut context = Context::from_waker(Waker::noop());
        assert!(future.as_mut().poll(&mut context).is_pending());
        sender.try_send(2).unwrap();
        assert_eq!(
            future.as_mut().poll(&mut context),
            Poll::Ready(Ok((2, true)))
        );
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
