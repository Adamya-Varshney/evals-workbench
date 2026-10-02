import { Notice, PageHeader } from "../components/ui";

export function Later({ title }: { title: string }) {
  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <PageHeader title={title} />
      <Notice>This stage is built in a later phase of the build plan.</Notice>
    </div>
  );
}
