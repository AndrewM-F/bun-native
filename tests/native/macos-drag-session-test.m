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
        if (isfinite(sessionPoint.x) || isfinite(sessionPoint.y)) {
            fprintf(stderr, "Old session position leaked\n");
            return 2;
        }
        primaryHeight = 800;
        [view draggingSession:(NSDraggingSession *)(id)[FakeSession new]
                 movedToPoint:NSMakePoint(362, 445)];
        CGPoint point;
        if (session_moves(&point) != 1 || point.x != 362 || point.y != 355) {
            fprintf(stderr, "First session movement was not recorded\n");
            return 3;
        }
        [view mouseDown:event];
        if (session_moves(&point) != 0 || isfinite(point.x) || isfinite(point.y)) {
            fprintf(stderr, "Movement was not reset for the second session\n");
            return 4;
        }
        [view draggingSession:(NSDraggingSession *)(id)[FakeSession new]
                 movedToPoint:NSMakePoint(120, 650)];
        if (session_moves(&point) != 1 || point.x != 120 || point.y != 150) {
            fprintf(stderr, "Second session movement was not recorded\n");
            return 5;
        }
        NSDictionary *bounds = CFBridgingRelease(CGRectCreateDictionaryRepresentation(
            CGRectMake(100, 100, 80, 80)));
        NSMutableArray *windows = [NSMutableArray array];
        for (int index = 0; index < 22; index++) {
            [windows addObject:@{ (__bridge NSString *)kCGWindowBounds: bounds,
                (__bridge NSString *)kCGWindowNumber: @(index),
                (__bridge NSString *)kCGWindowOwnerPID: @100,
                (__bridge NSString *)kCGWindowLayer: @0,
                (__bridge NSString *)kCGWindowAlpha: @1,
                (__bridge NSString *)kCGWindowName: @"private title" }];
        }
        [windows addObject:@{ (__bridge NSString *)kCGWindowBounds: bounds }];
        NSDictionary *stack = windows_at_point(windows, CGPointMake(110, 110));
        NSArray *reported = stack[@"windows"];
        if ([stack[@"matchingCount"] intValue] != 22 || ![stack[@"truncated"] boolValue] ||
            reported.count != 20 || [reported[0][@"id"] intValue] != 0 ||
            [reported[19][@"id"] intValue] != 19 || [reported[0] count] != 5) {
            fprintf(stderr, "Window stack evidence was not bounded or ordered\n");
            return 6;
        }
        if ([windows_at_point(windows, CGPointMake(300, 300))[@"matchingCount"] intValue] != 0) {
            fprintf(stderr, "Window stack included windows outside the point\n");
            return 7;
        }
        return 0;
    }
}
