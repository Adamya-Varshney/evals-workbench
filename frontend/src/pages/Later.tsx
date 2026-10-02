import { Notice, PageHeader } from "../components/ui";

export function Later({ title }: { title: string }) {
  return (
    <div className="mx-auto max-w-4xl px-8 py-10">
      <PageHeader title={title} />
      <Notice>This stage is built in a later phase of the build plan.</Notice>
    </div>
  );
}
