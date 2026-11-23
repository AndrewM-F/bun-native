// Exercise the source's per-session movement evidence without moving a pointer.
#define main drag_source_main
#include "macos-drag-source.m"
#undef main

@interface FakeSession : NSObject
@property BOOL animatesToStartingPositionsOnCancelOrFail;
@property NSDraggingFormation draggingFormation;
@property (readonly) NSPasteboard *draggingPasteboard;
@end
@implementation FakeSession
- (NSPasteboard *)draggingPasteboard {
    return [NSPasteboard pasteboardWithUniqueName];
}
@end

@interface FakeSource : SourceView
@end
@implementation FakeSource
- (NSDraggingSession *)beginDraggingSessionWithItems:(NSArray<NSDraggingItem *> *)items
                                               event:(NSEvent *)event
                                              source:(id<NSDraggingSource>)source {
    (void)items;
    (void)event;
    (void)source;
    return (NSDraggingSession *)(id)[FakeSession new];
}
@end

int main(void) {
    @autoreleasepool {
        sessionLock = [NSObject new];
        began = dispatch_semaphore_create(0);
        payload = @[@"previous session"];
        sessionMoves = 5;
        sessionPoint = CGPointMake(362, 355);
        FakeSource *view = [FakeSource new];
        NSEvent *event = [NSEvent mouseEventWithType:NSEventTypeLeftMouseDown
            location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:0
            context:nil eventNumber:0 clickCount:1 pressure:1];
        [view mouseDown:event];
        if (sessionMoves != 0) {
            fprintf(stderr, "Old session movement leaked: %ld\n", (long)sessionMoves);
            return 1;
        }
        if (isfinite(sessionPoint.x) || isfinite(sessionPoint.y)) return 2;
        primaryHeight = 800;
        [view draggingSession:(NSDraggingSession *)(id)[FakeSession new]
                 movedToPoint:NSMakePoint(362, 445)];
        CGPoint point;
        if (session_moves(&point) != 1 || point.x != 362 || point.y != 355) return 3;
        [view mouseDown:event];
        if (session_moves(&point) != 0 || isfinite(point.x) || isfinite(point.y)) return 4;
        [view draggingSession:(NSDraggingSession *)(id)[FakeSession new]
                 movedToPoint:NSMakePoint(120, 650)];
        if (session_moves(&point) != 1 || point.x != 120 || point.y != 150) return 5;
        return 0;
    }
}
