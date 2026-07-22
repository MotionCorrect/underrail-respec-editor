using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Diagnostics;
using System.Linq;
using System.Security.Cryptography;
using Mono.Cecil;
using Mono.Cecil.Cil;

namespace UnderrailRuntimePatcher
{
    internal sealed class ModScan { public string Id=""; public bool Implemented=true; public int CandidateCount; public string Target=""; public string Details=""; }

    internal static class Program
    {
        private static int Main(string[] args)
        {
            try
            {
                if (args.Length == 0 || args[0] == "help" || args[0] == "--help") { Usage(); return 0; }
                var command = args[0].ToLowerInvariant();
                var opts = ParseArgs(args.Skip(1).ToArray());
                var gameDir = GetOption(opts, "game-dir", Directory.GetCurrentDirectory());
                var assembly = ResolveAssembly(gameDir, GetOption(opts, "assembly", null));
                switch (command)
                {
                    case "scan": case "dry-run": PrintScan(assembly); return 0;
                    case "patch": PatchMods(assembly, SplitMods(GetOption(opts, "mods", "throwing_chance_cap")), GetDouble(opts, "cap", 0.99), GetDouble(opts, "weight-multiplier", 0.1), GetBool(opts, "dry-run", false), GetBool(opts, "experimental", false)); return 0;
                    case "rollback": Rollback(assembly, GetOption(opts, "backup", null)); return 0;
                    case "status": PrintStatus(assembly); return 0;
                    default: throw new ArgumentException($"Unknown command '{command}'.");
                }
            }
            catch (Exception ex) { Console.Error.WriteLine("ERROR: " + ex.Message); return 1; }
        }

        private static void Usage()
        {
            Console.WriteLine("UnderrailRuntimePatcher");
            Console.WriteLine("  scan --game-dir <Underrail folder>");
            Console.WriteLine("  patch --game-dir <Underrail folder> --mods item_weight,force_restock,traders_buy_all,throwing_chance_cap --cap 0.99 --weight-multiplier 0.1 [--dry-run]");
            Console.WriteLine("  patch --game-dir <Underrail folder> --mods fastforward --experimental [--dry-run]  # experimental; failed live launch smoke test on build 21973456");
            Console.WriteLine("  rollback --game-dir <Underrail folder> --backup <backup-file>");
        }

        private static Dictionary<string,string> ParseArgs(string[] args){ var d=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase); for(int i=0;i<args.Length;i++){ if(!args[i].StartsWith("--")) continue; var k=args[i].Substring(2); if(i+1<args.Length&&!args[i+1].StartsWith("--")) d[k]=args[++i]; else d[k]="true";} return d; }
        private static string GetOption(Dictionary<string,string> o,string k,string f)=>o.TryGetValue(k,out var v)?v:f;
        private static bool GetBool(Dictionary<string,string> o,string k,bool f)=>o.TryGetValue(k,out var v)?bool.Parse(v):f;
        private static double GetDouble(Dictionary<string,string> o,string k,double f)=>o.TryGetValue(k,out var v)?double.Parse(v,CultureInfo.InvariantCulture):f;
        private static List<string> SplitMods(string s)=>s.Split(',').Select(x=>x.Trim()).Where(x=>x.Length>0).ToList();
        private static string ResolveAssembly(string gameDir,string explicitAssembly){ var p=!string.IsNullOrWhiteSpace(explicitAssembly)?explicitAssembly:Path.Combine(gameDir,"underrail.exe"); if(!File.Exists(p)) throw new FileNotFoundException("Underrail assembly not found",p); return Path.GetFullPath(p); }
        private static ReaderParameters ReaderParams(string p){ var r=new DefaultAssemblyResolver(); r.AddSearchDirectory(Path.GetDirectoryName(p)); return new ReaderParameters{AssemblyResolver=r,ReadWrite=false,InMemory=true}; }
        private static IEnumerable<TypeDefinition> AllTypes(ModuleDefinition m){ foreach(var t in m.Types){ yield return t; foreach(var n in Nested(t)) yield return n; } }
        private static IEnumerable<TypeDefinition> Nested(TypeDefinition t){ foreach(var n in t.NestedTypes){ yield return n; foreach(var x in Nested(n)) yield return x; } }
        private static IEnumerable<MethodDefinition> AllMethods(ModuleDefinition m)=>AllTypes(m).SelectMany(t=>t.Methods);
        private static bool IsLdcR8(Instruction i,double v)=>i.OpCode==OpCodes.Ldc_R8&&i.Operand is double d&&Math.Abs(d-v)<0.0000001;
        private static int CountLdcR8(MethodDefinition m,double v)=>m.HasBody?m.Body.Instructions.Count(i=>IsLdcR8(i,v)):0;
        private static string Json(string v)=>(v??"").Replace("\\","\\\\").Replace("\"","\\\"");

        private static List<MethodDefinition> ThrowingTargets(ModuleDefinition mod, double capValue)
        {
            return AllMethods(mod).Where(m=>m.HasBody && !m.IsConstructor && m.ReturnType.FullName=="System.Double[]" && m.Parameters.Count>=4 && CountLdcR8(m,capValue)>=3 && CountLdcR8(m,0.15)>0 && CountLdcR8(m,0.4)>0 && CountLdcR8(m,0.6)>0 && CountLdcR8(m,0.8)>0).ToList();
        }
        private static TypeDefinition CohType(ModuleDefinition mod)=>AllTypes(mod).SingleOrDefault(t=>t.FullName=="coh");
        private static List<MethodDefinition> ItemWeightTargets(ModuleDefinition mod){ var t=CohType(mod); if(t==null) return new List<MethodDefinition>(); return t.Properties.Where(p=>p.Name=="Weight"||p.Name=="SingleItemWeight").Select(p=>p.GetMethod).Where(m=>m!=null&&m.HasBody&&m.ReturnType.FullName=="System.Double").ToList(); }
        private static MethodDefinition ForceRestockTarget(ModuleDefinition mod)=>AllMethods(mod).SingleOrDefault(m=>m.FullName=="System.Void dvp::aqc(System.Boolean)");
        private static List<MethodDefinition> TradersBuyAllTargets(ModuleDefinition mod){ var type=AllTypes(mod).SingleOrDefault(t=>t.FullName=="b6o"); if(type==null) return new List<MethodDefinition>(); return type.Methods.Where(m=>m.FullName=="System.Boolean b6o::c()"||m.FullName=="System.Void b6o::e()"||m.FullName=="System.Boolean b6o::aeg(coh)").ToList(); }

        private static MethodDefinition FastforwardTarget(ModuleDefinition mod)=>AllMethods(mod).SingleOrDefault(m=>m.FullName=="System.Void e6d::.ctor(Microsoft.Xna.Framework.GameTime,Microsoft.Xna.Framework.Input.MouseState,Microsoft.Xna.Framework.Input.KeyboardState)");

        private static List<ModScan> Scan(string assembly)
        {
            using(var asm=AssemblyDefinition.ReadAssembly(assembly,ReaderParams(assembly))){ var mod=asm.MainModule; return new List<ModScan>{
                new ModScan{Id="throwing_chance_cap",CandidateCount=ThrowingTargets(mod,0.9).Count,Target=string.Join("; ",ThrowingTargets(mod,0.9).Select(m=>$"{m.FullName} RVA {m.RVA}")),Details="Diverclaim 0.9 throwing cap constant cluster; zero candidates may mean already patched."},
                new ModScan{Id="item_weight",CandidateCount=ItemWeightTargets(mod).Count,Target=string.Join("; ",ItemWeightTargets(mod).Select(m=>$"{m.FullName} RVA {m.RVA}")),Details="coh Weight and SingleItemWeight getters."},
                new ModScan{Id="force_restock",CandidateCount=ForceRestockTarget(mod)==null?0:1,Target=ForceRestockTarget(mod)?.FullName??"",Details="merchant restock method dvp::aqc(bool); patch forces boolean argument true."},
                new ModScan{Id="traders_buy_all",CandidateCount=TradersBuyAllTargets(mod).Count,Target=string.Join("; ",TradersBuyAllTargets(mod).Select(m=>$"{m.FullName} RVA {m.RVA}")),Details="barter UI restriction methods b6o::c/e/aeg."},
                new ModScan{Id="fastforward",Implemented=true,CandidateCount=FastforwardTarget(mod)==null?0:1,Target=FastforwardTarget(mod)?.FullName??"",Details="e6d GameTime input wrapper; injects tilde-held 10x elapsed GameTime helper."}
            }; }
        }

        private static void PrintScan(string assembly)
        {
            var scans=Scan(assembly); Console.WriteLine("{"); Console.WriteLine($"  \"assembly\": \"{Json(assembly)}\","); Console.WriteLine($"  \"sha256\": \"{Sha256(assembly)}\","); Console.WriteLine("  \"mods\": {");
            for(int i=0;i<scans.Count;i++){ var s=scans[i]; Console.WriteLine($"    \"{s.Id}\": {{\"implemented\": {s.Implemented.ToString().ToLowerInvariant()}, \"candidate_count\": {s.CandidateCount}, \"target\": \"{Json(s.Target)}\", \"details\": \"{Json(s.Details)}\"}}"+(i+1==scans.Count?"":",")); }
            Console.WriteLine("  }"); Console.WriteLine("}");
        }
        private static void PrintStatus(string assembly)=>PrintScan(assembly);

        private static void PatchMods(string assembly, List<string> mods, double cap, double weightMultiplier, bool dryRun, bool experimental)
        {
            if(cap<0.15||cap>1.0) throw new ArgumentOutOfRangeException(nameof(cap),"cap must be 0.15..1.0");
            if(weightMultiplier<0||weightMultiplier>1.0) throw new ArgumentOutOfRangeException(nameof(weightMultiplier),"weight multiplier must be 0..1");
            if(!dryRun) EnsureTargetAssemblyNotRunning(assembly);
            using(var asm=AssemblyDefinition.ReadAssembly(assembly,ReaderParams(assembly))){ ValidatePatchSet(asm.MainModule,mods,experimental); }
            if(dryRun){ Console.WriteLine($"DRY-RUN: would patch mods [{string.Join(",",mods)}]"); return; }
            var backup=BackupFile(assembly);
            try{
                using(var asm=AssemblyDefinition.ReadAssembly(assembly,ReaderParams(assembly))){ var changed=new Dictionary<string,int>(); foreach(var mod in mods){ switch(mod){
                    case "throwing_chance_cap": changed[mod]=PatchThrowing(asm.MainModule,cap); break;
                    case "item_weight": changed[mod]=PatchItemWeight(asm.MainModule,weightMultiplier); break;
                    case "force_restock": changed[mod]=PatchForceRestock(asm.MainModule); break;
                    case "traders_buy_all": changed[mod]=PatchTradersBuyAll(asm.MainModule); break;
                    case "fastforward": changed[mod]=PatchFastforward(asm.MainModule); break;
                    default: throw new InvalidOperationException($"Unknown or unimplemented mod '{mod}'."); } }
                    asm.Write(assembly); Console.WriteLine("{"); Console.WriteLine("  \"patched\": true,"); Console.WriteLine($"  \"mods\": \"{Json(string.Join(",",mods))}\","); Console.WriteLine($"  \"backup\": \"{Json(backup)}\","); Console.WriteLine("  \"changes\": {"); int i=0; foreach(var kv in changed) Console.WriteLine($"    \"{kv.Key}\": {kv.Value}"+(++i==changed.Count?"":",")); Console.WriteLine("  }"); Console.WriteLine("}"); }
            } catch { File.Copy(backup,assembly,true); throw; }
        }

        private static void ValidatePatchSet(ModuleDefinition mod,List<string> mods,bool experimental){ foreach(var m in mods){ switch(m){ case "throwing_chance_cap": if(ThrowingTargets(mod,0.9).Count!=1) throw new InvalidOperationException("throwing_chance_cap requires exactly one unpatched 0.9 target; maybe already patched."); break; case "item_weight": if(ItemWeightTargets(mod).Count!=2) throw new InvalidOperationException("item_weight requires Weight and SingleItemWeight getters."); break; case "force_restock": if(ForceRestockTarget(mod)==null) throw new InvalidOperationException("force_restock target not found."); break; case "traders_buy_all": if(TradersBuyAllTargets(mod).Count!=3) throw new InvalidOperationException("traders_buy_all requires three barter targets."); break; case "fastforward": if(!experimental) throw new InvalidOperationException("fastforward is experimental and failed live launch smoke testing; pass --experimental only for debugging."); if(FastforwardTarget(mod)==null) throw new InvalidOperationException("fastforward target not found."); break; default: throw new InvalidOperationException($"Unknown or unimplemented mod '{m}'."); } } }
        private static int PatchThrowing(ModuleDefinition mod,double cap){ var m=ThrowingTargets(mod,0.9).Single(); int c=0; foreach(var i in m.Body.Instructions) if(IsLdcR8(i,0.9)){ i.Operand=cap; c++; } return c; }
        private static int PatchItemWeight(ModuleDefinition mod,double multiplier){ int c=0; foreach(var m in ItemWeightTargets(mod)){ var il=m.Body.GetILProcessor(); var rets=m.Body.Instructions.Where(i=>i.OpCode==OpCodes.Ret).ToList(); foreach(var ret in rets){ il.InsertBefore(ret, il.Create(OpCodes.Ldc_R8,multiplier)); il.InsertBefore(ret, il.Create(OpCodes.Mul)); c++; } } return c; }
        private static int PatchForceRestock(ModuleDefinition mod){ var m=ForceRestockTarget(mod); var il=m.Body.GetILProcessor(); var first=m.Body.Instructions[0]; il.InsertBefore(first, il.Create(OpCodes.Ldc_I4_1)); il.InsertBefore(first, il.Create(OpCodes.Starg_S,m.Parameters[0])); return 1; }
        private static int PatchTradersBuyAll(ModuleDefinition mod){ int c=0; foreach(var m in TradersBuyAllTargets(mod)){ var il=m.Body.GetILProcessor(); var first=m.Body.Instructions[0]; if(m.ReturnType.FullName=="System.Boolean"){ il.InsertBefore(first,il.Create(OpCodes.Ldc_I4_0)); il.InsertBefore(first,il.Create(OpCodes.Ret)); } else { il.InsertBefore(first,il.Create(OpCodes.Ret)); } c++; } return c; }


        private static int PatchFastforward(ModuleDefinition mod)
        {
            var ctor=FastforwardTarget(mod);
            if(ctor==null) throw new InvalidOperationException("fastforward target not found");
            var helper=EnsureFastforwardHelper(mod, ctor.Parameters[0].ParameterType);
            var il=ctor.Body.GetILProcessor();
            int changed=0;
            foreach(var ins in ctor.Body.Instructions.ToList())
            {
                if(ins.OpCode==OpCodes.Stfld && ins.Operand is FieldReference fr && fr.FieldType.FullName==ctor.Parameters[0].ParameterType.FullName)
                {
                    il.InsertBefore(ins, il.Create(OpCodes.Call, helper));
                    changed++;
                }
            }
            if(changed!=1) throw new InvalidOperationException($"Expected one GameTime field assignment, found {changed}");
            return changed;
        }

        private static MethodReference EnsureFastforwardHelper(ModuleDefinition mod, TypeReference gameTimeType)
        {
            var existing=AllTypes(mod).FirstOrDefault(t=>t.FullName=="UnderrailRespecRuntimeMods");
            if(existing!=null) return existing.Methods.Single(m=>m.Name=="ApplyFastforward");
            var obj=mod.TypeSystem.Object;
            var type=new TypeDefinition("", "UnderrailRespecRuntimeMods", TypeAttributes.Public|TypeAttributes.Abstract|TypeAttributes.Sealed|TypeAttributes.BeforeFieldInit, obj);
            mod.Types.Add(type);
            var method=new MethodDefinition("ApplyFastforward", MethodAttributes.Public|MethodAttributes.Static, gameTimeType);
            method.Parameters.Add(new ParameterDefinition("original", ParameterAttributes.None, gameTimeType));
            type.Methods.Add(method);
            var refs=AllMethods(mod).Where(m=>m.HasBody).SelectMany(m=>m.Body.Instructions).Select(i=>i.Operand).OfType<MethodReference>().ToList();
            var getTotal=refs.First(m=>m.FullName=="System.TimeSpan Microsoft.Xna.Framework.GameTime::get_TotalGameTime()");
            var getElapsed=refs.First(m=>m.FullName=="System.TimeSpan Microsoft.Xna.Framework.GameTime::get_ElapsedGameTime()");
            var keyboardGet=refs.First(m=>m.FullName=="Microsoft.Xna.Framework.Input.KeyboardState Microsoft.Xna.Framework.Input.Keyboard::GetState()");
            var isKeyDown=refs.First(m=>m.FullName=="System.Boolean Microsoft.Xna.Framework.Input.KeyboardState::IsKeyDown(Microsoft.Xna.Framework.Input.Keys)");
            var getTicks=refs.First(m=>m.FullName=="System.Int64 System.TimeSpan::get_Ticks()");
            var fromTicks=refs.First(m=>m.FullName=="System.TimeSpan System.TimeSpan::FromTicks(System.Int64)");
            var gtCtor=refs.First(m=>m.FullName=="System.Void Microsoft.Xna.Framework.GameTime::.ctor(System.TimeSpan,System.TimeSpan)");
            var il=method.Body.GetILProcessor();
            method.Body.InitLocals=false;
            var returnOrig=Instruction.Create(OpCodes.Ldarg_0);
            il.Append(Instruction.Create(OpCodes.Call, mod.ImportReference(keyboardGet)));
            il.Append(Instruction.Create(OpCodes.Ldc_I4, 192));
            il.Append(Instruction.Create(OpCodes.Call, mod.ImportReference(isKeyDown)));
            il.Append(Instruction.Create(OpCodes.Brfalse_S, returnOrig));
            il.Append(Instruction.Create(OpCodes.Ldarg_0));
            il.Append(Instruction.Create(OpCodes.Call, mod.ImportReference(getTotal)));
            il.Append(Instruction.Create(OpCodes.Ldarg_0));
            il.Append(Instruction.Create(OpCodes.Call, mod.ImportReference(getElapsed)));
            il.Append(Instruction.Create(OpCodes.Call, mod.ImportReference(getTicks)));
            il.Append(Instruction.Create(OpCodes.Ldc_I8, 10L));
            il.Append(Instruction.Create(OpCodes.Mul));
            il.Append(Instruction.Create(OpCodes.Call, mod.ImportReference(fromTicks)));
            il.Append(Instruction.Create(OpCodes.Newobj, mod.ImportReference(gtCtor)));
            il.Append(Instruction.Create(OpCodes.Ret));
            il.Append(returnOrig);
            il.Append(Instruction.Create(OpCodes.Ret));
            return method;
        }

        private static void EnsureTargetAssemblyNotRunning(string assembly)
        {
            if(!string.Equals(Path.GetFileName(assembly), "underrail.exe", StringComparison.OrdinalIgnoreCase)) return;
            try
            {
                if(Process.GetProcessesByName("underrail").Any())
                    throw new InvalidOperationException("Underrail is running. Close the game before patching or rolling back underrail.exe.");
            }
            catch(InvalidOperationException) { throw; }
            catch { }
        }

        private static string BackupFile(string path){ var dir=Path.Combine(Path.GetDirectoryName(path),"underrail_respec_backups"); Directory.CreateDirectory(dir); var stamp=DateTime.Now.ToString("yyyyMMdd-HHmmss",CultureInfo.InvariantCulture); var b=Path.Combine(dir,Path.GetFileName(path)+"."+stamp+".bak"); File.Copy(path,b,false); return b; }
        private static void Rollback(string assembly,string backup){ EnsureTargetAssemblyNotRunning(assembly); if(string.IsNullOrWhiteSpace(backup)) throw new ArgumentException("--backup is required"); if(!File.Exists(backup)) throw new FileNotFoundException("Backup not found",backup); var rb=BackupFile(assembly); File.Copy(backup,assembly,true); Console.WriteLine("{"); Console.WriteLine("  \"rolled_back\": true,"); Console.WriteLine($"  \"restored_from\": \"{Json(Path.GetFullPath(backup))}\","); Console.WriteLine($"  \"pre_rollback_backup\": \"{Json(rb)}\""); Console.WriteLine("}"); }
        private static string Sha256(string path){ using(var sha=SHA256.Create()) using(var s=File.OpenRead(path)) return BitConverter.ToString(sha.ComputeHash(s)).Replace("-","").ToLowerInvariant(); }
    }
}
