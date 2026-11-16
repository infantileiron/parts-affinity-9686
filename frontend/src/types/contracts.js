/** @typedef {{id:number,code:string,equipment:string,parts:string[],note:string,revision:number,occupied_by:number|null}} Job */
/** @typedef {{id:number,name:string,state:string,result:object}} MiningRun */
/** @typedef {{id:number,run_id:number,antecedent:string[],consequent:string[],support:float,confidence:float,lift:float}} AssociationRule */
/** @typedef {{id:number,name:string,rule_id:number,parts:string[],note:string,status:string,revision:number}} Kit */
/** @typedef {{job_id:number,code:string,kit_ids:number[],kit_names:string[],required_parts:string[],union_parts:string[],idle_parts:string[]}} PlanAllocation */
/** @typedef {{job_id:number,code:string,required_parts:string[],missing:{part:string,reason:string,detail:string}[]}} PlanUncovered */
/** @typedef {{id:number,name:string,state:'draft'|'active'|'cancelled',carry_limit:number,basis:object,fingerprint:string,result:object,created_at:string,activated_at:string|null,cancelled_at:string|null}} KittingPlan */
