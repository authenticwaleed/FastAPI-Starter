import { ConsoleLink } from "@/components/console/console-link";
import { BackLink, PageHeader } from "@/components/page-header";

/**
 * The top of a console screen.
 *
 * Now the same component the customer app uses, with the console's own
 * link passed in. Sharing the primitive is allowed and sharing navigation
 * is not -- these are the two surfaces' *headings*, not their menus, and a
 * page title that behaved differently on one of them would be a difference
 * with nothing behind it.
 *
 * The back link is load-bearing here in a way it is not in the customer
 * app: a workspace's members, subscription, usage and integrations are
 * four separate screens precisely so that opening one does not read the
 * other three, and the way back has to be a link somebody follows rather
 * than a fan-out somebody pays for. Hence `ConsoleLink`, which does not
 * prefetch.
 */
export function ConsoleHeading({
  title,
  description,
  back,
  actions,
  meta,
}: {
  title: string;
  description?: React.ReactNode;
  back?: { href: string; label: string };
  actions?: React.ReactNode;
  meta?: React.ReactNode;
}) {
  return (
    <PageHeader
      title={title}
      description={description}
      meta={meta}
      actions={actions}
      back={
        back ? (
          <BackLink href={back.href} label={back.label} as={ConsoleLink} />
        ) : null
      }
    />
  );
}
