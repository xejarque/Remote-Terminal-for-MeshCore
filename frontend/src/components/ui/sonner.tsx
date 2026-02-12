import { Toaster as Sonner, toast } from 'sonner';

type ToasterProps = React.ComponentProps<typeof Sonner>;

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="dark"
      className="toaster group"
      toastOptions={{
        classNames: {
          toast:
            'group toast group-[.toaster]:bg-card/95 group-[.toaster]:backdrop-blur-xl group-[.toaster]:text-foreground group-[.toaster]:border-border/50 group-[.toaster]:shadow-2xl group-[.toaster]:rounded-xl',
          description: 'group-[.toast]:text-muted-foreground',
          actionButton: 'group-[.toast]:bg-primary group-[.toast]:text-primary-foreground',
          cancelButton: 'group-[.toast]:bg-muted group-[.toast]:text-muted-foreground',
          error:
            'group-[.toaster]:bg-[#1a0e10]/95 group-[.toaster]:text-red-300 group-[.toaster]:border-red-500/20 [&_[data-description]]:text-red-400/70',
          success:
            'group-[.toaster]:bg-[#0e1a12]/95 group-[.toaster]:text-emerald-300 group-[.toaster]:border-emerald-500/20 [&_[data-description]]:text-emerald-400/70',
        },
      }}
      {...props}
    />
  );
};

export { Toaster, toast };
