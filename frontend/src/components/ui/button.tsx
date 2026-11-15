import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

// One size: 44px tall, the touch target floor. One filled variant, used once per screen.
const buttonVariants = cva(
  "inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-sm border px-4 text-sm font-bold tracking-widest whitespace-nowrap uppercase select-none motion-safe:transition-colors disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "border-primary bg-primary text-primary-foreground hover:bg-primary/85",
        outline: "border-input bg-transparent hover:bg-muted aria-expanded:bg-muted",
        secondary: "border-input bg-muted hover:bg-border",
        ghost: "border-transparent hover:bg-muted",
        destructive: "border-destructive bg-transparent text-destructive hover:bg-destructive/10",
        link: "border-transparent underline underline-offset-4",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
