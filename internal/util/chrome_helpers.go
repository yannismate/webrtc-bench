package util

import (
	"context"
	"github.com/chromedp/cdproto/runtime"
	"github.com/chromedp/chromedp"
)

func ExposeFunc(name string, f func(string)) chromedp.Action {
	return chromedp.Tasks{
		chromedp.ActionFunc(func(ctx context.Context) error {
			chromedp.ListenTarget(ctx, func(ev interface{}) {
				if ev, ok := ev.(*runtime.EventBindingCalled); ok && ev.Name == name {
					f(ev.Payload)
				}
			})
			return nil
		}),
		runtime.AddBinding(name),
	}
}
